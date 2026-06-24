import { Router, Request, Response } from 'express';
import { Module } from '../../handlers/moduleInit';
import logger from '../../handlers/logger';
import prisma from '../../db';
import crypto from 'crypto';

declare module 'express-session' {
  interface SessionData {
    oauthState?: string;
  }
}

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

      // Generate a secure random state and store in session
      const state = crypto.randomBytes(16).toString('hex');
      req.session.oauthState = state;
      logger.info('[OAuth started] Redirecting to Discord with state protection');

      const authorizationUrl = `https://discord.com/api/oauth2/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=code&scope=identify%20email&state=${state}`;
      res.redirect(authorizationUrl);
    });

    router.get('/auth/discord/callback', async (req: Request, res: Response) => {
      const { code, state, error } = req.query;

      // Handle OAuth errors first (e.g. access_denied)
      if (error) {
        logger.warn(`[Login failed] Discord OAuth error callback: ${error}`);
        if (error === 'access_denied') {
          return res.redirect('/login?err=discord_access_denied');
        }
        return res.redirect('/login?err=discord_auth_failed');
      }

      // Verify state parameters strictly
      const storedState = req.session.oauthState;
      req.session.oauthState = undefined; // clear immediately

      if (!state || state !== storedState) {
        logger.error(`[Login failed] State validation failed. Received: ${state}, Stored: ${storedState}`);
        return res.redirect('/login?err=discord_auth_failed');
      }
      logger.info('[State verified] Success');

      if (!code) {
        logger.error('[Login failed] Callback received without code.');
        return res.redirect('/login?err=discord_auth_failed');
      }

      const clientId = process.env.DISCORD_CLIENT_ID;
      const clientSecret = process.env.DISCORD_CLIENT_SECRET;
      const redirectUri = process.env.DISCORD_REDIRECT_URI;
      const ownerId = process.env.DISCORD_OWNER_ID;

      if (!clientId || !clientSecret || !redirectUri || !ownerId) {
        logger.error('Discord OAuth config variables are missing.');
        return res.redirect('/login?err=discord_config_error');
      }

      try {
        // Exchange code for access token
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
          logger.error('[Login failed] Token exchange failed:', errBody);
          return res.redirect('/login?err=discord_token_error');
        }

        const tokenData = await tokenResponse.json() as { access_token: string };
        logger.info('[Token exchange successful]');

        // Fetch user profile info
        const userResponse = await fetch('https://discord.com/api/users/@me', {
          headers: {
            Authorization: `Bearer ${tokenData.access_token}`,
          },
        });

        if (!userResponse.ok) {
          const errBody = await userResponse.text();
          logger.error('[Login failed] Discord API fetch failed:', errBody);
          return res.redirect('/login?err=discord_user_error');
        }

        const discordUser = await userResponse.json() as {
          id: string;
          username: string;
          global_name?: string;
          email?: string;
          avatar?: string;
        };

        if (!discordUser.id) {
          logger.error('[Login failed] Received invalid Discord user profile.');
          return res.redirect('/login?err=discord_invalid_user');
        }
        logger.info(`[Profile retrieved] ${discordUser.username} (${discordUser.id})`);

        // Generate avatar URL fallback
        let avatarUrl: string;
        if (discordUser.avatar) {
          avatarUrl = `https://cdn.discordapp.com/avatars/${discordUser.id}/${discordUser.avatar}.${discordUser.avatar.startsWith('a_') ? 'gif' : 'png'}`;
        } else {
          const defaultIdx = Number(BigInt(discordUser.id) >> 22n) % 6;
          avatarUrl = `https://cdn.discordapp.com/embed/avatars/${defaultIdx}.png`;
        }

        // Search user by discordId strictly
        let user = await prisma.users.findUnique({
          where: { discordId: discordUser.id },
        });

        // Determine if they are the admin
        const shouldBeAdmin = discordUser.id === ownerId;

        if (!user) {
          // Fallback email to satisfy non-nullable UNIQUE constraint in schema
          const userEmail = discordUser.email || `discord-${discordUser.id}@pilotpanel.local`;

          // Generate secure random password to prevent default password attacks
          const randomPassword = crypto.randomBytes(32).toString('hex');

          // Create a new user (strictly Discord-only ID basis, no email linking)
          user = await prisma.users.create({
            data: {
              discordId: discordUser.id,
              discordUsername: discordUser.username,
              discordGlobalName: discordUser.global_name || discordUser.username,
              discordAvatar: discordUser.avatar || null,
              discordAvatarUrl: avatarUrl,
              email: userEmail,
              username: discordUser.username,
              password: randomPassword,
              isAdmin: shouldBeAdmin,
              description: 'Aviation Cockpit User',
              avatar: discordUser.avatar || null,
            },
          });
          logger.info(`[User created] ID: ${user.id} discord: ${discordUser.id}`);
        } else {
          // Update profile fields only
          user = await prisma.users.update({
            where: { id: user.id },
            data: {
              discordUsername: discordUser.username,
              discordGlobalName: discordUser.global_name || discordUser.username,
              discordAvatar: discordUser.avatar || null,
              discordAvatarUrl: avatarUrl,
              isAdmin: shouldBeAdmin,
              avatar: discordUser.avatar || user.avatar,
            },
          });
        }

        // Regenerate session to prevent session fixation attacks
        await new Promise<void>((resolve, reject) =>
          req.session.regenerate((err) => (err ? reject(err) : resolve()))
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
            ipAddress: req.ip || '',
            userAgent: req.headers['user-agent'] || null,
          },
        });

        logger.info(`[User logged in] ${user.username} (ID: ${user.id})`);
        res.redirect('/');
      } catch (error) {
        logger.error('[Login failed] Discord authentication callback database/session error:', error);
        res.redirect('/login?err=discord_error');
      }
    });

    return router;
  },
};

export default authModule;
