import { LXCManager } from '../handlers/lxc';
import logger from '../logger';

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function handleLxcCreate(req: Request): Promise<Response> {
  let body: {
    name?: string;
    os?: string;
    cpu?: number;
    ram?: number;
    disk?: number;
    password?: string;
  };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, os, cpu, ram, disk, password } = body;
  if (!name || !os || !cpu || !ram || !disk || !password) {
    return json({ error: 'missing required fields: name, os, cpu, ram, disk, password' }, 400);
  }

  try {
    // We launch this as a promise but return response, or block since deploy can take time?
    // Let's await it.
    await LXCManager.deployContainer(name, os, cpu, ram, disk, password);
    return json({ success: true, message: `Container ${name} deployed successfully` });
  } catch (err: any) {
    logger.error(`LXC deploy error for ${name}:`, err);
    return json({ error: err.message || 'failed to deploy container' }, 500);
  }
}

export async function handleLxcAction(req: Request): Promise<Response> {
  let body: {
    name?: string;
    action?: 'start' | 'stop' | 'restart' | 'suspend' | 'resume';
  };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, action } = body;
  if (!name || !action) {
    return json({ error: 'name and action are required' }, 400);
  }

  try {
    await LXCManager.executeAction(name, action);
    return json({ success: true, message: `Action ${action} executed successfully` });
  } catch (err: any) {
    logger.error(`LXC action error for ${name} (${action}):`, err);
    return json({ error: err.message || 'failed to execute action' }, 500);
  }
}

export async function handleLxcDestroy(req: Request): Promise<Response> {
  let body: { name?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name } = body;
  if (!name) {
    return json({ error: 'name is required' }, 400);
  }

  try {
    await LXCManager.destroyContainer(name);
    return json({ success: true, message: `Container ${name} destroyed` });
  } catch (err: any) {
    logger.error(`LXC destroy error for ${name}:`, err);
    return json({ error: err.message || 'failed to destroy container' }, 500);
  }
}

export async function handleLxcStats(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const name = url.searchParams.get('name');
  const cpu = parseInt(url.searchParams.get('cpu') ?? '1', 10);
  const ram = parseInt(url.searchParams.get('ram') ?? '512', 10);
  const disk = parseInt(url.searchParams.get('disk') ?? '10', 10);
  const status = url.searchParams.get('status') ?? 'stopped';

  if (!name) {
    return json({ error: 'name is required' }, 400);
  }

  try {
    const stats = await LXCManager.getContainerStats(name, cpu, ram, disk, status);
    return json(stats);
  } catch (err: any) {
    logger.error(`LXC stats error for ${name}:`, err);
    return json({ error: err.message || 'failed to get container stats' }, 500);
  }
}

export async function handleLxcPassword(req: Request): Promise<Response> {
  let body: { name?: string; password?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, password } = body;
  if (!name || !password) {
    return json({ error: 'name and password are required' }, 400);
  }

  try {
    await LXCManager.changePassword(name, password);
    return json({ success: true, message: 'Password updated successfully' });
  } catch (err: any) {
    logger.error(`LXC password error for ${name}:`, err);
    return json({ error: err.message || 'failed to change password' }, 500);
  }
}

export async function handleLxcSnapshot(req: Request): Promise<Response> {
  let body: { name?: string; snapshotName?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, snapshotName } = body;
  if (!name || !snapshotName) {
    return json({ error: 'name and snapshotName are required' }, 400);
  }

  try {
    await LXCManager.createSnapshot(name, snapshotName);
    return json({ success: true, message: `Snapshot ${snapshotName} created` });
  } catch (err: any) {
    logger.error(`LXC snapshot error for ${name}:`, err);
    return json({ error: err.message || 'failed to create snapshot' }, 500);
  }
}

export async function handleLxcRestore(req: Request): Promise<Response> {
  let body: { name?: string; snapshotName?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, snapshotName } = body;
  if (!name || !snapshotName) {
    return json({ error: 'name and snapshotName are required' }, 400);
  }

  try {
    await LXCManager.restoreSnapshot(name, snapshotName);
    return json({ success: true, message: `Snapshot ${snapshotName} restored` });
  } catch (err: any) {
    logger.error(`LXC restore error for ${name}:`, err);
    return json({ error: err.message || 'failed to restore snapshot' }, 500);
  }
}

export async function handleLxcDeleteSnapshot(req: Request): Promise<Response> {
  let body: { name?: string; snapshotName?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, snapshotName } = body;
  if (!name || !snapshotName) {
    return json({ error: 'name and snapshotName are required' }, 400);
  }

  try {
    await LXCManager.deleteSnapshot(name, snapshotName);
    return json({ success: true, message: `Snapshot ${snapshotName} deleted` });
  } catch (err: any) {
    logger.error(`LXC delete snapshot error for ${name}:`, err);
    return json({ error: err.message || 'failed to delete snapshot' }, 500);
  }
}

// File system routes

export async function handleLxcFileList(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const name = url.searchParams.get('name');
  const path = url.searchParams.get('path') ?? '/';

  if (!name) {
    return json({ error: 'name is required' }, 400);
  }

  try {
    const files = await LXCManager.listFiles(name, path);
    return json(files);
  } catch (err: any) {
    logger.error(`LXC list files error for ${name} at ${path}:`, err);
    return json({ error: err.message || 'failed to list files' }, 500);
  }
}

export async function handleLxcFileRead(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const name = url.searchParams.get('name');
  const path = url.searchParams.get('path');

  if (!name || !path) {
    return json({ error: 'name and path are required' }, 400);
  }

  try {
    const content = await LXCManager.readFile(name, path);
    return new Response(content, {
      status: 200,
      headers: { 'Content-Type': 'text/plain' },
    });
  } catch (err: any) {
    logger.error(`LXC read file error for ${name} at ${path}:`, err);
    return json({ error: err.message || 'failed to read file' }, 500);
  }
}

export async function handleLxcFileWrite(req: Request): Promise<Response> {
  let body: { name?: string; path?: string; content?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, path, content } = body;
  if (!name || !path || content === undefined) {
    return json({ error: 'name, path, and content are required' }, 400);
  }

  try {
    await LXCManager.writeFile(name, path, content);
    return json({ success: true, message: 'File written successfully' });
  } catch (err: any) {
    logger.error(`LXC write file error for ${name} at ${path}:`, err);
    return json({ error: err.message || 'failed to write file' }, 500);
  }
}

export async function handleLxcFileDelete(req: Request): Promise<Response> {
  let body: { name?: string; path?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, path } = body;
  if (!name || !path) {
    return json({ error: 'name and path are required' }, 400);
  }

  try {
    await LXCManager.deleteFile(name, path);
    return json({ success: true, message: 'File deleted successfully' });
  } catch (err: any) {
    logger.error(`LXC delete file error for ${name} at ${path}:`, err);
    return json({ error: err.message || 'failed to delete file' }, 500);
  }
}

export async function handleLxcFileMkdir(req: Request): Promise<Response> {
  let body: { name?: string; path?: string };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return json({ error: 'invalid json body' }, 400);
  }

  const { name, path } = body;
  if (!name || !path) {
    return json({ error: 'name and path are required' }, 400);
  }

  try {
    await LXCManager.createDirectory(name, path);
    return json({ success: true, message: 'Directory created successfully' });
  } catch (err: any) {
    logger.error(`LXC create directory error for ${name} at ${path}:`, err);
    return json({ error: err.message || 'failed to create directory' }, 500);
  }
}
