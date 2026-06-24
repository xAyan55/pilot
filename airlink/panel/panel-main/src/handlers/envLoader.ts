/**
 * ╳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╳
 *      AirLink - Open Source Project by AirlinkLabs
 *      Repository: https://github.com/airlinklabs/panel
 *
 *     © 2025 AirlinkLabs. Licensed under the MIT License
 * ╳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╳
 */

import fs from 'fs';
import path from 'path';
import logger from './logger';
import dotenv from 'dotenv';

// Required env vars that must be set for the panel to function.
// If any are missing after .env load, the panel exits immediately.
const REQUIRED_ENV_VARS = [
  'SESSION_SECRET',
  'DATABASE_URL',
  'DISCORD_CLIENT_ID',
  'DISCORD_CLIENT_SECRET',
  'DISCORD_REDIRECT_URI',
  'DISCORD_OWNER_ID'
];

// Optional vars from example.env — warn if not set, don't exit.
const EXAMPLE_ENV_PATH = path.resolve(process.cwd(), 'example.env');

export function loadEnv() {
  const envPath = path.resolve(process.cwd(), '.env');

  try {
    const data = fs.readFileSync(envPath, 'utf8');
    const parsed = dotenv.parse(data);
    for (const [key, value] of Object.entries(parsed)) {
      if (process.env[key] === undefined || process.env[key] === '') {
        process.env[key] = value;
      }
    }
  } catch (error) {
    logger.error('Error loading .env file:', error);
  }

  // Provide safe defaults/fallbacks for core database and session config if missing or empty
  if (!process.env.DATABASE_URL || process.env.DATABASE_URL.trim() === '') {
    process.env.DATABASE_URL = 'file:./storage/dev.db';
  }
  if (!process.env.SESSION_SECRET || process.env.SESSION_SECRET.trim() === '') {
    process.env.SESSION_SECRET = 'change_me_super_secret';
  }

  // Print startup diagnostics for core variables
  console.log('\nStartup Diagnostics:');
  const varsToCheck = [
    'DATABASE_URL',
    'SESSION_SECRET',
    'DISCORD_CLIENT_ID',
    'DISCORD_CLIENT_SECRET',
    'DISCORD_REDIRECT_URI',
    'DISCORD_OWNER_ID'
  ];
  varsToCheck.forEach((key) => {
    const status = process.env[key] ? 'LOADED' : 'MISSING';
    console.log(`  ${key}: ${status}`);
  });
  console.log();

  // Fail-fast: ensure required env vars are set
  for (const key of REQUIRED_ENV_VARS) {
    if (!process.env[key]) {
      console.error(`[env] FATAL: required env var ${key} is not set. Add it to .env`);
      process.exit(1);
    }
  }

  // Warn for optional vars defined in example.env
  try {
    const exampleData = fs.readFileSync(EXAMPLE_ENV_PATH, 'utf8');
    for (const line of exampleData.split('\n')) {
      const eqIndex = line.indexOf('=');
      if (eqIndex === -1) continue;
      const key = line.slice(0, eqIndex).trim();
      if (key && !process.env[key]) {
        logger.warn(`[env] optional env var ${key} is not set (see example.env)`);
      }
    }
  } catch {
    // example.env is optional
  }
}
