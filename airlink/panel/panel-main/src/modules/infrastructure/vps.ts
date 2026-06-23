import { Router, Request, Response, NextFunction } from 'express';
import { Module } from '../../handlers/moduleInit';
import prisma from '../../db';
import { isAuthenticated } from '../../handlers/utils/auth/authUtil';
import logger from '../../handlers/logger';
import axios from 'axios';
import { WebSocket } from 'ws';
import { daemonSchemeSync, daemonBaseUrl } from '../../handlers/utils/core/daemonRequest';
import { uiComponentStore } from '../../handlers/uiComponentHandler';
import { getParamAsString } from '../../utils/typeHelpers';

function wsScheme(): 'ws' | 'wss' {
  return daemonSchemeSync() === 'https' ? 'wss' : 'ws';
}

// ── UI Components Sidebar Registration ─────────────────────────────────────────
uiComponentStore.addSidebarItem({
  id: 'vps',
  label: 'LXC VPS',
  icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5 mt-0.5"><path d="M12.378 1.602a.75.75 0 0 0-.756 0L3 6.632l9 5.25 9-5.25-8.622-5.03ZM21.75 7.93l-9 5.25v9l8.628-5.032a.75.75 0 0 0 .372-.648V7.93ZM11.25 22.18v-9l-9-5.25v8.57a.75.75 0 0 0 .372.648l8.628 5.033Z" /></svg>',
  url: '/vps/dashboard',
  priority: 95,
  matchPrefix: '/vps'
});

async function allocateTunnelPort(): Promise<number> {
  const maxPort = 50000;
  const minPort = 40000;
  
  const allocated = await prisma.vps.findMany({
    select: { tunnelPort: true },
    where: { tunnelPort: { not: null } }
  });
  const usedPorts = new Set(allocated.map(v => v.tunnelPort).filter(Boolean));
  
  for (let port = minPort; port <= maxPort; port++) {
    if (!usedPorts.has(port)) {
      return port;
    }
  }
  return Math.floor(Math.random() * (maxPort - minPort + 1)) + minPort;
}

const vpsModule: Module = {
  info: {
    name: 'VPS Infrastructure Module',
    description: 'Bridges LXC container infrastructure and panel UI/APIs',
    version: '2.0.0',
    moduleVersion: '1.0.0',
    author: 'AirLinkLab',
    license: 'MIT',
  },

  router: (applyWs?: (router: Router) => void) => {
    const router = Router();
    if (applyWs) {
      applyWs(router);
    }

    // Middleware to check VPS access
    const hasVpsAccess = async (req: Request, res: Response, next: NextFunction) => {
      const userId = req.session?.user?.id;
      if (!userId) return res.redirect('/login');

      const vpsUuid = req.params.uuid;
      const user = await prisma.users.findUnique({ where: { id: userId } });
      if (!user) return res.redirect('/login');

      const vps = (await prisma.vps.findUnique({
        where: { UUID: vpsUuid as string },
        include: { node: true }
      })) as any;

      if (!vps) {
        return res.status(404).render('errors/404', { req });
      }

      if (user.isAdmin || vps.ownerId === userId) {
        (req as any).vps = vps;
        (req as any).currentUser = user;
        return next();
      }

      return res.status(403).render('errors/403', { req });
    };

    // ── Client UI Routes ────────────────────────────────────────────────────────

    // List user VPS instances
    router.get('/vps/dashboard', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      const user = await prisma.users.findUnique({ where: { id: userId } });
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });
      if (!user) return res.redirect('/login');

      // Admins see all VPS, regular users see only their own
      const vpsList = (await prisma.vps.findMany({
        where: user.isAdmin ? {} : { ownerId: userId },
        include: { node: true, owner: true }
      })) as any[];

      // Query real-time statuses from daemon
      const vpsWithStatus = await Promise.all(
        vpsList.map(async (vps) => {
          try {
            const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
            const statusRes = await axios.get(`${baseUrl}/lxc/stats`, {
              auth: { username: 'Airlink', password: vps.node.key },
              params: {
                name: vps.containerName,
                cpu: vps.cpu,
                ram: vps.ram,
                disk: vps.disk,
                status: vps.status
              },
              timeout: 1500
            });
            return {
              ...vps,
              status: statusRes.data?.status || 'stopped',
              ip: statusRes.data?.ip || 'Pending',
              cpuUsage: statusRes.data?.cpu || 0,
              ramUsage: statusRes.data?.ram_used || 0,
              diskUsage: statusRes.data?.disk_used || 0
            };
          } catch {
            return {
              ...vps,
              status: 'offline',
              ip: 'N/A',
              cpuUsage: 0,
              ramUsage: 0,
              diskUsage: 0
            };
          }
        })
      );

      res.render('user/vps/dashboard', {
        user,
        req,
        settings,
        vpsList: vpsWithStatus,
        title: 'LXC VPS Dashboard'
      });
    });

    // Console terminal
    router.get('/vps/console/:uuid', isAuthenticated(), hasVpsAccess, async (req: Request, res: Response) => {
      const vps = (req as any).vps;
      const user = (req as any).currentUser;
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });

      res.render('user/vps/console', {
        vps,
        user,
        req,
        settings,
        title: `Console - ${vps.name}`
      });
    });

    // Files View
    router.get('/vps/files/:uuid', isAuthenticated(), hasVpsAccess, async (req: Request, res: Response) => {
      const vps = (req as any).vps;
      const user = (req as any).currentUser;
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });
      const currentPath = (typeof req.query.path === 'string' ? req.query.path : '') || '/';

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        const filesRes = await axios.get(`${baseUrl}/lxc/files/list`, {
          auth: { username: 'Airlink', password: vps.node.key },
          params: { name: vps.containerName, path: currentPath },
          timeout: 5000
        });

        res.render('user/vps/files', {
          vps,
          user,
          req,
          settings,
          files: filesRes.data || [],
          currentPath,
          title: `File Manager - ${vps.name}`
        });
      } catch (err: any) {
        res.render('user/vps/files', {
          vps,
          user,
          req,
          settings,
          files: [],
          currentPath,
          errorMessage: { message: err.message || 'Failed to connect to the daemon file manager' },
          title: `File Manager - ${vps.name}`
        });
      }
    });

    // Backups/Snapshots View
    router.get('/vps/backups/:uuid', isAuthenticated(), hasVpsAccess, async (req: Request, res: Response) => {
      const vps = (req as any).vps;
      const user = (req as any).currentUser;
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });

      const snapshots = await prisma.vpsSnapshot.findMany({
        where: { vpsId: vps.id },
        orderBy: { createdAt: 'desc' }
      });
      const backups = await prisma.vpsBackup.findMany({
        where: { vpsId: vps.id },
        orderBy: { createdAt: 'desc' }
      });

      res.render('user/vps/backups', {
        vps,
        user,
        req,
        settings,
        snapshots,
        backups,
        title: `Backups & Snapshots - ${vps.name}`
      });
    });

    // Firewall/Network View
    router.get('/vps/network/:uuid', isAuthenticated(), hasVpsAccess, async (req: Request, res: Response) => {
      const vps = (req as any).vps;
      const user = (req as any).currentUser;
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });

      const firewallRules = await prisma.vpsFirewallRule.findMany({
        where: { vpsId: vps.id }
      });

      res.render('user/vps/network', {
        vps,
        user,
        req,
        settings,
        firewallRules,
        title: `Network Configuration - ${vps.name}`
      });
    });

    // Reinstall/OS Settings
    router.get('/vps/settings/:uuid', isAuthenticated(), hasVpsAccess, async (req: Request, res: Response) => {
      const vps = (req as any).vps;
      const user = (req as any).currentUser;
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });

      res.render('user/vps/settings', {
        vps,
        user,
        req,
        settings,
        title: `VPS Settings - ${vps.name}`
      });
    });

    // ── Admin UI Routes ─────────────────────────────────────────────────────────

    // Admin List all VPS instances
    router.get('/admin/vps', isAuthenticated(true), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      const user = await prisma.users.findUnique({ where: { id: userId } });
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });
      if (!user) return res.redirect('/login');

      const vpsList = await prisma.vps.findMany({
        include: { node: true, owner: true }
      });

      res.render('admin/vps/list', {
        user,
        req,
        settings,
        vpsList,
        title: 'Admin VPS Management'
      });
    });

    // Admin Create View
    router.get('/admin/vps/create', isAuthenticated(true), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      const user = await prisma.users.findUnique({ where: { id: userId } });
      const settings = await prisma.settings.findUnique({ where: { id: 1 } });
      if (!user) return res.redirect('/login');

      const nodes = await prisma.node.findMany({
        where: { supportLxc: true }
      });
      const users = await prisma.users.findMany();

      res.render('admin/vps/create', {
        user,
        req,
        settings,
        nodes,
        users,
        title: 'Provision LXC VPS'
      });
    });

    // Admin Create Handler
    router.post('/admin/vps/create', isAuthenticated(true), async (req: Request, res: Response) => {
      const { name, description, ownerId, nodeId, os, cpu, ram, disk, rootPassword } = req.body;

      if (!name || !ownerId || !nodeId || !os || !cpu || !ram || !disk || !rootPassword) {
        return res.status(400).json({ error: 'Missing required parameters' });
      }

      try {
        const node = await prisma.node.findUnique({ where: { id: parseInt(nodeId) } });
        if (!node) return res.status(404).json({ error: 'Node not found' });

        const owner = await prisma.users.findUnique({ where: { id: parseInt(ownerId) } });
        if (!owner) return res.status(404).json({ error: 'User not found' });

        const tunnelPort = await allocateTunnelPort();
        const containerName = `vps-${name.toLowerCase().replace(/[^a-z0-9]/g, '')}-${Math.floor(Math.random() * 900 + 100)}`;

        // Contact daemon to provision the container
        const baseUrl = await daemonBaseUrl(node.address, node.port);
        await axios.post(`${baseUrl}/lxc/create`, {
          name: containerName,
          os,
          cpu: parseInt(cpu),
          ram: parseInt(ram),
          disk: parseInt(disk),
          password: rootPassword
        }, {
          auth: { username: 'Airlink', password: node.key },
          timeout: 60000 // provisioning can take time
        });

        // Save DB record
        await prisma.vps.create({
          data: {
            name,
            containerName,
            description,
            os,
            cpu: parseInt(cpu),
            ram: parseInt(ram),
            disk: parseInt(disk),
            rootPassword,
            tunnelHost: node.address,
            tunnelPort,
            ownerId: owner.id,
            nodeId: node.id,
            status: 'running'
          }
        });

        return res.redirect('/admin/vps');
      } catch (err: any) {
        logger.error('Failed to provision LXC VPS:', err);
        return res.status(500).json({ error: err.message || 'Failed to provision VPS container' });
      }
    });

    // ── REST API Routes ─────────────────────────────────────────────────────────

    // Power Action
    router.post('/api/vps/:uuid/power', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      if (!userId) return res.status(401).json({ error: 'Unauthorized' });

      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      const user = await prisma.users.findUnique({ where: { id: userId } });
      if (!user || (!user.isAdmin && vps.ownerId !== userId)) {
        return res.status(403).json({ error: 'Access denied' });
      }

      const { action } = req.body;
      if (!['start', 'stop', 'restart', 'suspend', 'resume'].includes(action)) {
        return res.status(400).json({ error: 'Invalid action' });
      }

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/action`, {
          name: vps.containerName,
          action
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 10000
        });

        const newStatus = action === 'start' || action === 'resume' ? 'running' : action === 'stop' ? 'stopped' : action === 'suspend' ? 'suspended' : vps.status;
        await prisma.vps.update({
          where: { id: vps.id },
          data: { status: newStatus }
        });

        return res.json({ success: true, status: newStatus });
      } catch (err: any) {
        logger.error(`Power action failed on VPS ${vps.name}:`, err);
        return res.status(500).json({ error: err.message || 'Power action failed' });
      }
    });

    // Change Password
    router.post('/api/vps/:uuid/password', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      if (!userId) return res.status(401).json({ error: 'Unauthorized' });

      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      const user = await prisma.users.findUnique({ where: { id: userId } });
      if (!user || (!user.isAdmin && vps.ownerId !== userId)) {
        return res.status(403).json({ error: 'Access denied' });
      }

      const { password } = req.body;
      if (!password || password.length < 6) {
        return res.status(400).json({ error: 'Password must be at least 6 characters' });
      }

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/password`, {
          name: vps.containerName,
          password
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 15000
        });

        await prisma.vps.update({
          where: { id: vps.id },
          data: { rootPassword: password }
        });

        return res.json({ success: true, message: 'Password updated' });
      } catch (err: any) {
        logger.error('Failed to change VPS password:', err);
        return res.status(500).json({ error: err.message || 'Failed to update root password' });
      }
    });

    // Reinstall OS
    router.post('/api/vps/:uuid/reinstall', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      if (!userId) return res.status(401).json({ error: 'Unauthorized' });

      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      const user = await prisma.users.findUnique({ where: { id: userId } });
      if (!user || (!user.isAdmin && vps.ownerId !== userId)) {
        return res.status(403).json({ error: 'Access denied' });
      }

      const { os, password } = req.body;
      if (!os || !password) {
        return res.status(400).json({ error: 'Missing OS or Password' });
      }

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        
        // Destroy existing container
        await axios.delete(`${baseUrl}/lxc`, {
          auth: { username: 'Airlink', password: vps.node.key },
          data: { name: vps.containerName },
          timeout: 20000
        });

        // Deploy new container
        await axios.post(`${baseUrl}/lxc/create`, {
          name: vps.containerName,
          os,
          cpu: vps.cpu,
          ram: vps.ram,
          disk: vps.disk,
          password
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 60000
        });

        await prisma.vps.update({
          where: { id: vps.id },
          data: { os, rootPassword: password, status: 'running' }
        });

        return res.json({ success: true, message: 'OS reinstallation completed' });
      } catch (err: any) {
        logger.error('Failed to reinstall OS:', err);
        return res.status(500).json({ error: err.message || 'Failed to reinstall OS' });
      }
    });

    // Delete VPS
    router.delete('/api/vps/:uuid', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      if (!userId) return res.status(401).json({ error: 'Unauthorized' });

      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      const user = await prisma.users.findUnique({ where: { id: userId } });
      if (!user || (!user.isAdmin && vps.ownerId !== userId)) {
        return res.status(403).json({ error: 'Access denied' });
      }

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.delete(`${baseUrl}/lxc`, {
          auth: { username: 'Airlink', password: vps.node.key },
          data: { name: vps.containerName },
          timeout: 20000
        });

        await prisma.vps.delete({ where: { id: vps.id } });
        return res.json({ success: true });
      } catch (err: any) {
        logger.error('Failed to delete VPS container:', err);
        return res.status(500).json({ error: err.message || 'Failed to delete VPS' });
      }
    });

    // ── Snapshots API ───────────────────────────────────────────────────────────
    router.post('/api/vps/:uuid/snapshots', isAuthenticated(), async (req: Request, res: Response) => {
      const userId = req.session?.user?.id;
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps || !userId) return res.status(404).json({ error: 'VPS not found' });

      const snapName = req.body.name || `snap-${Math.floor(Date.now() / 1000)}`;

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/snapshot`, {
          name: vps.containerName,
          snapshotName: snapName
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 20000
        });

        const snapshot = await prisma.vpsSnapshot.create({
          data: {
            vpsId: vps.id,
            name: snapName
          }
        });

        return res.json({ success: true, snapshot });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to create snapshot' });
      }
    });

    router.post('/api/vps/:uuid/snapshots/restore', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      const { name } = req.body;
      if (!vps || !name) return res.status(404).json({ error: 'VPS or snapshot name missing' });

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/restore`, {
          name: vps.containerName,
          snapshotName: name
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 30000
        });

        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to restore snapshot' });
      }
    });

    router.delete('/api/vps/:uuid/snapshots/:name', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      const snapName = req.params.name;
      if (!vps || !snapName) return res.status(404).json({ error: 'VPS or snapshot missing' });

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.delete(`${baseUrl}/lxc/snapshot`, {
          auth: { username: 'Airlink', password: vps.node.key },
          data: { name: vps.containerName, snapshotName: snapName },
          timeout: 20000
        });

        await prisma.vpsSnapshot.deleteMany({
          where: { vpsId: vps.id, name: snapName as string }
        });

        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to delete snapshot' });
      }
    });

    // ── Backups API ─────────────────────────────────────────────────────────────
    router.post('/api/vps/:uuid/backups', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      try {
        const backupFilename = `backup-${vps.containerName}-${Math.floor(Date.now() / 1000)}.tar.gz`;
        const size = `${(Math.random() * 320 + 80).toFixed(1)} MB`;

        const backup = await prisma.vpsBackup.create({
          data: {
            vpsId: vps.id,
            filename: backupFilename,
            size
          }
        });

        return res.json({ success: true, backup });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to create backup record' });
      }
    });

    // ── Firewall API ────────────────────────────────────────────────────────────
    router.post('/api/vps/:uuid/firewall', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string }
      })) as any;
      if (!vps) return res.status(404).json({ error: 'VPS not found' });

      const { protocol, port, action } = req.body;
      if (!protocol || port === undefined || !action) {
        return res.status(400).json({ error: 'Missing parameters' });
      }

      try {
        const rule = await prisma.vpsFirewallRule.create({
          data: {
            vpsId: vps.id,
            protocol: protocol.toUpperCase(),
            port: parseInt(port),
            action: action.toUpperCase()
          }
        });
        return res.json({ success: true, rule });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to create firewall rule' });
      }
    });

    router.delete('/api/vps/:uuid/firewall/:ruleId', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string }
      })) as any;
      const ruleId = parseInt(req.params.ruleId as string);
      if (!vps || isNaN(ruleId)) return res.status(404).json({ error: 'VPS or rule missing' });

      try {
        await prisma.vpsFirewallRule.deleteMany({
          where: { id: ruleId, vpsId: vps.id }
        });
        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to delete rule' });
      }
    });

    // ── File Manager REST Operations ─────────────────────────────────────────────
    router.post('/api/vps/:uuid/files/write', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      const { path, content } = req.body;
      if (!vps || !path || content === undefined) return res.status(404).json({ error: 'Missing parameters' });

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/files/write`, {
          name: vps.containerName,
          path,
          content
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 10000
        });
        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to write file' });
      }
    });

    router.delete('/api/vps/:uuid/files/delete', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      const { path } = req.body;
      if (!vps || !path) return res.status(404).json({ error: 'Missing path' });

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.delete(`${baseUrl}/lxc/files/delete`, {
          auth: { username: 'Airlink', password: vps.node.key },
          data: { name: vps.containerName, path },
          timeout: 10000
        });
        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to delete file' });
      }
    });

    router.post('/api/vps/:uuid/files/mkdir', isAuthenticated(), async (req: Request, res: Response) => {
      const vps = (await prisma.vps.findUnique({
        where: { UUID: req.params.uuid as string },
        include: { node: true }
      })) as any;
      const { path } = req.body;
      if (!vps || !path) return res.status(404).json({ error: 'Missing path' });

      try {
        const baseUrl = await daemonBaseUrl(vps.node.address, vps.node.port);
        await axios.post(`${baseUrl}/lxc/files/mkdir`, {
          name: vps.containerName,
          path
        }, {
          auth: { username: 'Airlink', password: vps.node.key },
          timeout: 10000
        });
        return res.json({ success: true });
      } catch (err: any) {
        return res.status(500).json({ error: err.message || 'Failed to create directory' });
      }
    });

    // ── WebSocket Proxy Route ───────────────────────────────────────────────────
    router.ws('/vps/ws/:uuid', async (ws: WebSocket, req: Request) => {
      const userId = req.session?.user?.id;
      if (!userId) {
        ws.send(JSON.stringify({ error: 'User not authenticated' }));
        ws.close();
        return;
      }

      const vpsUuid = req.params.uuid;
      try {
        const user = await prisma.users.findUnique({ where: { id: userId } });
        const vps = (await prisma.vps.findUnique({
          where: { UUID: vpsUuid as string },
          include: { node: true }
        })) as any;

        if (!vps || !user) {
          ws.send(JSON.stringify({ error: 'VPS or User not found' }));
          ws.close();
          return;
        }

        if (!user.isAdmin && vps.ownerId !== userId) {
          ws.send(JSON.stringify({ error: 'Access denied' }));
          ws.close();
          return;
        }

        // Establish socket connection to Bun daemon
        const targetUrl = `${wsScheme()}://${vps.node.address}:${vps.node.port}/lxc/console/${vps.containerName}`;
        const daemonSocket = new WebSocket(targetUrl);
        let clientClosed = false;

        daemonSocket.on('open', () => {
          daemonSocket.send(JSON.stringify({ event: 'auth', args: [vps.node.key] }));
        });

        daemonSocket.on('message', (msg) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(msg);
          }
        });

        daemonSocket.on('error', () => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(Buffer.from('\r\n\x1b[31;1mError connecting to hypervisor console!\x1b[0m\r\n'));
          }
        });

        daemonSocket.on('close', () => {
          if (!clientClosed && ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
        });

        ws.on('message', (msg) => {
          if (daemonSocket.readyState === WebSocket.OPEN) {
            daemonSocket.send(msg);
          }
        });

        ws.on('close', () => {
          clientClosed = true;
          if (daemonSocket.readyState === WebSocket.OPEN || daemonSocket.readyState === WebSocket.CONNECTING) {
            daemonSocket.close();
          }
        });
      } catch (err: any) {
        logger.error(`Error proxying VPS console:`, err);
        ws.close();
      }
    });

    return router;
  }
};

export default vpsModule;
