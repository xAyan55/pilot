import { Router, Request, Response } from 'express';
import { Module } from '../../handlers/moduleInit';
import logger from '../../handlers/logger';
import prisma from '../../db';

const authModule: Module = {
  info: {
    name: 'Auth Module',
    description: 'This file is for authentication and authorization of users via Discord OAuth.',
    version: '2.0.0',
    moduleVersion: '1.0.0',
    author: 'AirLinkLab',
    license: 'MIT',
  },

  router: () => {
    const router = Router();

    router.get('/login', async (req: Request, res: Response) => {
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });
      res.render('auth/login', { req, settings });
    });

    router.get('/register', async (req: Request, res: Response) => {
      res.redirect('/login');
    });

    router.get('/auth/discord', (req: Request, res: Response) => {
      const clientId = process.env.DISCORD_CLIENT_ID;
      const redirectUri = process.env.DISCORD_REDIRECT_URI;
      if (!clientId || !redirectUri) {
        logger.error('Discord Client ID or Redirect URI is missing in environment configuration.');
        return res.redirect('/login?err=discord_config_error');
      }
      const authorizationUrl = `https://discord.com/api/oauth2/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=code&scope=identify%20email`;
      res.redirect(authorizationUrl);
    });

    router.get('/auth/discord/callback', async (req: Request, res: Response) => {
      const { code } = req.query;
      if (!code) {
        return res.redirect('/login?err=discord_auth_failed');
      }

      const clientId = process.env.DISCORD_CLIENT_ID;
      const clientSecret = process.env.DISCORD_CLIENT_SECRET;
      const redirectUri = process.env.DISCORD_REDIRECT_URI;
      const adminUserId = process.env.DISCORD_ADMIN_USER_ID;

      if (!clientId || !clientSecret || !redirectUri) {
        logger.error('Discord OAuth config variables are missing.');
        return res.redirect('/login?err=discord_config_error');
      }

      try {
        // Exchange code for token
        const tokenResponse = await fetch('https://discord.com/api/oauth2/token', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            client_id: clientId,
            client_secret: clientSecret,
            grant_type: 'authorization_code',
            code: code as string,
            redirect_uri: redirectUri,
          }).toString(),
        });

        if (!tokenResponse.ok) {
          const errBody = await tokenResponse.text();
          logger.error('Discord token exchange failed:', errBody);
          return res.redirect('/login?err=discord_token_error');
        }

        const tokenData = await tokenResponse.json() as { access_token: string };

        // Fetch user info
        const userResponse = await fetch('https://discord.com/api/users/@me', {
          headers: {
            Authorization: `Bearer ${tokenData.access_token}`,
          },
        });

        if (!userResponse.ok) {
          logger.error('Discord user info fetch failed.');
          return res.redirect('/login?err=discord_user_error');
        }

        const discordUser = await userResponse.json() as { id: string; username: string; email?: string; avatar?: string };

        if (!discordUser.id) {
          return res.redirect('/login?err=discord_invalid_user');
        }

        // Check if user exists by discordId
        let user = await prisma.users.findUnique({
          where: { discordId: discordUser.id },
        });

        const userCount = await prisma.users.count();
        const isFirstUser = userCount === 0;

        const userEmail = discordUser.email || `${discordUser.username}@discord.local`;

        if (!user) {
          // Check if there is an existing user with the same email
          user = await prisma.users.findUnique({
            where: { email: userEmail },
          });

          if (user) {
            // Link existing user to Discord ID
            user = await prisma.users.update({
              where: { id: user.id },
              data: {
                discordId: discordUser.id,
                username: discordUser.username,
                avatar: discordUser.avatar || user.avatar,
              },
            });
          } else {
            // Create a new user
            const shouldBeAdmin = isFirstUser || (adminUserId && discordUser.id === adminUserId);
            user = await prisma.users.create({
              data: {
                discordId: discordUser.id,
                email: userEmail,
                username: discordUser.username,
                password: 'discord-auth-only',
                isAdmin: !!shouldBeAdmin,
                description: 'Aviation Cockpit User',
                avatar: discordUser.avatar || null,
              },
            });
          }
        } else {
          // Update username and email if changed, or check if admin ID matches now
          const shouldBeAdmin = user.isAdmin || isFirstUser || (adminUserId && discordUser.id === adminUserId);
          user = await prisma.users.update({
            where: { id: user.id },
            data: {
              username: discordUser.username,
              email: userEmail,
              isAdmin: !!shouldBeAdmin,
              avatar: discordUser.avatar || user.avatar,
            },
          });
        }

        // Set session
        await new Promise<void>((resolve, reject) =>
          req.session.regenerate(err => (err ? reject(err) : resolve()))
        );

        req.session.user = {
          id: user.id,
          email: user.email,
          isAdmin: user.isAdmin,
          description: user.description ?? '',
          username: user.username ?? '',
        };

        await prisma.loginHistory.create({
          data: {
            userId: user.id,
            ipAddress: req.ip,
            userAgent: req.headers['user-agent'] || null,
          },
        });

        res.redirect('/');
      } catch (error) {
        logger.error('Discord authentication callback error:', error);
        res.redirect('/login?err=discord_error');
      }
    });

    router.post('/logout', (req: Request, res: Response) => {
      if (req.session) {
        req.session.destroy((err) => {
          if (err) {
            logger.error('Session destruction error', err);
            return res.status(500).json({ error: 'logout_error' });
          }
          res.clearCookie('connect.sid');
          res.redirect('/');
        });
      } else {
        res.redirect('/');
      }
    });

    return router;
  },
};

export default authModule;
