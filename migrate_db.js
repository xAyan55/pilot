const Database = require('./airlink/panel/panel-main/node_modules/better-sqlite3');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PILOT_DB_PATH = path.resolve(__dirname, 'pilotpanel.db');
const AIRLINK_DB_PATH = path.resolve(__dirname, 'airlink/panel/panel-main/storage/dev.db');

function formatTimestamp(raw) {
  if (!raw) return new Date().toISOString();
  try {
    return new Date(raw).toISOString();
  } catch {
    return new Date().toISOString();
  }
}

function migrate() {
  if (!fs.existsSync(PILOT_DB_PATH)) {
    console.log(`Source database {PILOT_DB_PATH} not found. Skipping migration.`);
    return;
  }
  if (!fs.existsSync(AIRLINK_DB_PATH)) {
    console.log(`Destination database {AIRLINK_DB_PATH} not found. Make sure Prisma has initialized it.`);
    return;
  }

  console.log("Connecting to databases...");
  const dbSrc = new Database(PILOT_DB_PATH, { readonly: true });
  const dbDst = new Database(AIRLINK_DB_PATH);

  // Enable foreign key constraints in destination database for strict consistency
  dbDst.pragma('foreign_keys = ON');

  // 1. Migrate Nodes
  console.log("Migrating nodes...");
  const nodes = dbSrc.prepare("SELECT * FROM nodes").all();
  for (const node of nodes) {
    const exists = dbDst.prepare("SELECT id FROM Node WHERE id = ?").get(node.id);
    if (exists) {
      console.log(`Node ID ${node.id} already exists. Skipping.`);
      continue;
    }
    const nodeCreated = formatTimestamp(node.created_at);
    dbDst.prepare(`
      INSERT INTO Node (id, name, ram, cpu, disk, address, port, key, createdAt, allocatedPorts, sftpPort, supportDocker, supportLxc)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(node.id, node.name, 0, 0, 0, node.fqdn, node.port, node.api_key, nodeCreated, '[]', 3003, 1, 1);
    console.log(`Migrated node: ${node.name}`);
  }

  // 2. Migrate Users
  console.log("Migrating users...");
  const users = dbSrc.prepare("SELECT * FROM users").all();
  for (const user of users) {
    const exists = dbDst.prepare("SELECT id FROM Users WHERE id = ?").get(user.id);
    if (exists) {
      console.log(`User ID ${user.id} already exists. Skipping.`);
      continue;
    }
    const isAdmin = user.role === 'admin' ? 1 : 0;
    const userCreated = formatTimestamp(null);
    dbDst.prepare(`
      INSERT INTO Users (id, username, email, password, isAdmin, createdAt, updatedAt, description, avatar, permissions, serverLimit, maxMemory, maxCpu, maxStorage)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(user.id, user.username, user.email, user.password_hash, isAdmin, userCreated, userCreated, 'Migrated from PilotPanel', null, '[]', 5, 2048, 200, 10240);
    console.log(`Migrated user: ${user.username}`);
  }

  // 3. Migrate VPS instances
  console.log("Migrating VPS instances...");
  const vpsList = dbSrc.prepare("SELECT * FROM vps").all();
  for (const vps of vpsList) {
    const exists = dbDst.prepare("SELECT id FROM Vps WHERE id = ?").get(vps.id);
    if (exists) {
      console.log(`VPS ID ${vps.id} already exists. Skipping.`);
      continue;
    }
    
    // Ensure the node and owner exist in destination to prevent foreign key errors
    const userExists = dbDst.prepare("SELECT id FROM Users WHERE id = ?").get(vps.user_id);
    const nodeExists = dbDst.prepare("SELECT id FROM Node WHERE id = ?").get(vps.node_id);
    if (!userExists || !nodeExists) {
      console.log(`Skipping VPS ID ${vps.id} because owner or node does not exist in destination.`);
      continue;
    }

    const vpsUuid = crypto.randomUUID();
    const vpsCreated = formatTimestamp(vps.created_at);
    dbDst.prepare(`
      INSERT INTO Vps (id, UUID, name, containerName, description, createdAt, status, os, cpu, ram, disk, rootPassword, tunnelHost, tunnelPort, ownerId, nodeId)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(vps.id, vpsUuid, vps.name || vps.container_name, vps.container_name, 'Migrated VPS', vpsCreated, vps.status, vps.os, vps.cpu, vps.ram, vps.disk, vps.root_password, vps.tunnel_host, vps.tunnel_port, vps.user_id, vps.node_id);
    console.log(`Migrated VPS container: ${vps.container_name}`);
  }

  // 4. Migrate Snapshots
  console.log("Migrating snapshots...");
  const snapshots = dbSrc.prepare("SELECT * FROM snapshots").all();
  for (const snap of snapshots) {
    const exists = dbDst.prepare("SELECT id FROM VpsSnapshot WHERE id = ?").get(snap.id);
    if (exists) {
      console.log(`Snapshot ID ${snap.id} already exists. Skipping.`);
      continue;
    }
    const vpsExists = dbDst.prepare("SELECT id FROM Vps WHERE id = ?").get(snap.vps_id);
    if (!vpsExists) {
      console.log(`Orphaned snapshot ID ${snap.id} skipped (VPS ID ${snap.vps_id} not found).`);
      continue;
    }
    const snapCreated = formatTimestamp(snap.created_at);
    dbDst.prepare(`
      INSERT INTO VpsSnapshot (id, vpsId, name, createdAt)
      VALUES (?, ?, ?, ?)
    `).run(snap.id, snap.vps_id, snap.name, snapCreated);
    console.log(`Migrated snapshot: ${snap.name}`);
  }

  // 5. Migrate Backups
  console.log("Migrating backups...");
  const backups = dbSrc.prepare("SELECT * FROM backups").all();
  for (const backup of backups) {
    const exists = dbDst.prepare("SELECT id FROM VpsBackup WHERE id = ?").get(backup.id);
    if (exists) {
      console.log(`Backup ID ${backup.id} already exists. Skipping.`);
      continue;
    }
    const vpsExists = dbDst.prepare("SELECT id FROM Vps WHERE id = ?").get(backup.vps_id);
    if (!vpsExists) {
      console.log(`Orphaned backup ID ${backup.id} skipped (VPS ID ${backup.vps_id} not found).`);
      continue;
    }
    const backupCreated = formatTimestamp(backup.created_at);
    dbDst.prepare(`
      INSERT INTO VpsBackup (id, vpsId, filename, size, createdAt)
      VALUES (?, ?, ?, ?, ?)
    `).run(backup.id, backup.vps_id, backup.filename, backup.size, backupCreated);
    console.log(`Migrated backup: ${backup.filename}`);
  }

  // 6. Migrate Firewall Rules
  console.log("Migrating firewall rules...");
  const rules = dbSrc.prepare("SELECT * FROM firewall_rules").all();
  for (const rule of rules) {
    const exists = dbDst.prepare("SELECT id FROM VpsFirewallRule WHERE id = ?").get(rule.id);
    if (exists) {
      console.log(`Firewall rule ID ${rule.id} already exists. Skipping.`);
      continue;
    }
    const vpsExists = dbDst.prepare("SELECT id FROM Vps WHERE id = ?").get(rule.vps_id);
    if (!vpsExists) {
      console.log(`Orphaned firewall rule ID ${rule.id} skipped (VPS ID ${rule.vps_id} not found).`);
      continue;
    }
    dbDst.prepare(`
      INSERT INTO VpsFirewallRule (id, vpsId, protocol, port, action)
      VALUES (?, ?, ?, ?, ?)
    `).run(rule.id, rule.vps_id, rule.protocol, rule.port, rule.action);
    console.log(`Migrated firewall rule: ${rule.protocol} ${rule.port} ${rule.action}`);
  }

  console.log("Migration completed successfully!");
}

migrate();
