import { spawn } from 'child_process';
import type { ServerWebSocket } from 'bun';
import type { WsData } from './server';
import logger from '../logger';
import { IS_MOCK_LXC } from '../handlers/lxc';

export async function attachToLxcContainer(name: string, ws: ServerWebSocket<WsData>): Promise<void> {
  try {
    if (IS_MOCK_LXC) {
      // Mock terminal simulator
      ws.send("\r\n\x1b[33;1m--- Mock LXC Container Console (Non-Linux Host) ---\x1b[0m\r\n");
      ws.send("vps-node1# ");
      
      ws.data._logCleanup = () => {};
      return;
    }

    // Spawn lxc exec interactive shell
    const proc = spawn('lxc', ['exec', name, '--env', 'TERM=xterm-256color', '--', '/bin/bash'], {
      stdio: ['pipe', 'pipe', 'pipe']
    });

    proc.stdout.on('data', (chunk: Buffer) => {
      if (ws.readyState === 1) ws.send(chunk);
    });

    proc.stderr.on('data', (chunk: Buffer) => {
      if (ws.readyState === 1) ws.send(chunk);
    });

    proc.on('close', () => {
      if (ws.readyState === 1) {
        ws.send('\r\n\x1b[31;1m[Session ended]\x1b[0m\r\n');
        ws.close(1000, 'shell process closed');
      }
    });

    ws.data._logCleanup = () => {
      try {
        proc.kill();
      } catch {}
    };

    (ws.data as any).lxcStdin = proc.stdin;

  } catch (err) {
    logger.error(`Failed to attach to LXC container console for ${name}`, err);
    if (ws.readyState === 1) ws.close(1000, 'LXC connection error');
  }
}
