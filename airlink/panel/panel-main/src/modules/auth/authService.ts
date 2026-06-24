import bcrypt from 'bcryptjs';
import prisma from '../../db';
import { Router, Request, Response } from 'express';
import { Module } from '../../handlers/moduleInit';
import logger from '../../handlers/logger';
import rateLimit from 'express-rate-limit';

declare module 'express-session' {
  interface SessionData {
    user: {
      id: number;
      email: string;
      isAdmin: boolean;
      username: string;
      description: string;
    };
  }
}

// Tight rate limit applied only to auth routes — separate from the global limit.
// 10 attempts per minute per IP before they get a 429.
const authRateLimit = rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many attempts. Try again in a minute.' },
  keyGenerator: (req) => req.ip || req.socket?.remoteAddress || 'unknown',
  validate: false,
});

async function getSecuritySettings() {
  try {
    const s = await prisma.settings.findUnique({ where: { id: 1 } });
    return {
      maxAttempts:    s?.loginMaxAttempts    ?? 5,
      lockoutMinutes: s?.loginLockoutMinutes ?? 15,
    };
  } catch {
    return { maxAttempts: 5, lockoutMinutes: 15 };
  }
}

const authServiceModule: Module = {
  info: {
    name:          'Auth System Module',
    description:   'Authentication and authorisation for users.',
    version:          '2.0.0',
    moduleVersion: '2.0.0',
    author:        'AirlinkLab',
    license:       'MIT',
  },

  router: () => {
    const router = Router();

    // ── POST /login ─────────────────────────────────────────────────────────
    router.post('/login', (req: Request, res: Response) => {
      res.redirect('/login?err=discord_only');
    });

    // ── POST /register ───────────────────────────────────────────────────────
    router.post('/register', (req: Request, res: Response) => {
      res.redirect('/login?err=discord_only');
    });

    // ── ALL /logout ──────────────────────────────────────────────────────────
    router.all('/logout', (req: Request, res: Response) => {
      res.clearCookie('connect.sid');
      if (req.session) {
        req.session.destroy((err) => {
          if (err) {
            logger.error('[Logout failed] Session destruction error:', err);
          }
          res.redirect('/login');
        });
      } else {
        res.redirect('/login');
      }
    });

    return router;
  },
};

export default authServiceModule;
