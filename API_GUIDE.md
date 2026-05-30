# REST API v1 — Comprehensive Reference Guide

Welcome to the premium REST API v1 Reference for the LXC Control Panel. This guide outlines how to authenticate requests, make client-level API calls, and perform administrative system operations.

---

## 🔒 Authentication

All API endpoints reside under the `/api/v1` path. To make authenticated calls, you must provide your active 64-character API Key via the standard `Authorization` header as a Bearer token:

```http
Authorization: Bearer <your_api_key_here>
```

- **Client Keys**: Allow standard users to query and operate virtual servers assigned specifically to their own account.
- **Admin Keys**: Allow administrators to access all client data, query node statistics, register nodes, delete VPS, and suspend accounts.

---

## 🌎 Public Branding (No Auth)

### Get Public Branding Customization

Returns safe public details about the panel (e.g. colors, logo, site name). Useful for the Discord bot to automatically adapt its interface theme to your brand.

- **Endpoint**: `GET /api/v1/settings/public`
- **Authentication**: None
- **Response (`200 OK`)**:
  ```json
  {
    "color_accent": "#ABE7B2",
    "color_cool": "#93BFC7",
    "color_primary": "#ECF4E8",
    "color_secondary": "#CBF3BB",
    "favicon_url": "/static/branding/favicon.ico",
    "logo_url": "/static/branding/logo.png",
    "site_name": "MintyHost LXC"
  }
  ```

---

## 👤 User Profile Endpoints

### Get Profile Information

Returns info about the logged-in owner of the API key.

- **Endpoint**: `GET /api/v1/profile`
- **Request**:
  ```bash
  curl -X GET \
    -H "Authorization: Bearer <your_api_key>" \
    http://127.0.0.1:5000/api/v1/profile
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "id": 2,
    "username": "client01",
    "email": "client@mintyhost.net",
    "role": "client",
    "pfp": "/static/uploads/pfp_client.png"
  }
  ```

### Update Profile Email and Username

- **Endpoint**: `PUT /api/v1/profile`
- **Payload**:
  ```json
  {
    "username": "newusername",
    "email": "newemail@example.com"
  }
  ```
- **Request**:
  ```bash
  curl -X PUT \
    -H "Authorization: Bearer <your_api_key>" \
    -H "Content-Type: application/json" \
    -d '{"username": "newusername", "email": "newemail@example.com"}' \
    http://127.0.0.1:5000/api/v1/profile
  ```

### Change Account Password

- **Endpoint**: `PUT /api/v1/profile/password`
- **Payload**:
  ```json
  {
    "current_password": "OldPassword123",
    "new_password": "NewSecretPassword456"
  }
  ```

---

## 🖥️ Client Virtual Private Servers (VPS)

### List Assigned VPS

- **Endpoint**: `GET /api/v1/vps`
- **Request**:
  ```bash
  curl -H "Authorization: Bearer <your_api_key>" http://127.0.0.1:5000/api/v1/vps
  ```
- **Response (`200 OK`)**:
  ```json
  [
    {
      "id": 1,
      "user_id": 2,
      "node_id": 1,
      "name": "Dev Environment",
      "container_name": "vps-1-devenvironment",
      "os": "ubuntu/22.04",
      "cpu": 2,
      "ram": "4 GB",
      "disk": "80 GB",
      "bandwidth": "4 TB",
      "ip_address": "10.0.3.155",
      "root_password": "root_password_here",
      "status": "running",
      "tunnel_port": 40155,
      "tunnel_url": "https://pinggy-ssh-relay-url.net",
      "created_at": "2026-05-30 12:00:00"
    }
  ]
  ```

### Get Single VPS Details

- **Endpoint**: `GET /api/v1/vps/<vps_id>`

### Query Live VPS Utilization Statistics

- **Endpoint**: `GET /api/v1/vps/<vps_id>/stats`
- **Response (`200 OK`)**:
  ```json
  {
    "cpu_percent": 12.4,
    "ram_used_mb": 512,
    "ram_percent": 12.8,
    "disk_used_gb": 4.2,
    "disk_percent": 5.25,
    "status": "running"
  }
  ```

### Trigger VPS Power Action

Start, stop, or reboot a virtual server.

- **Endpoint**: `POST /api/v1/vps/<vps_id>/action`
- **Payload**:
  ```json
  {
    "action": "restart"  // Supported: "start", "stop", "restart"
  }
  ```
- **Request**:
  ```bash
  curl -X POST \
    -H "Authorization: Bearer <your_api_key>" \
    -H "Content-Type: application/json" \
    -d '{"action": "restart"}' \
    http://127.0.0.1:5000/api/v1/vps/1/action
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "status": "success",
    "message": "Action 'restart' initiated.",
    "new_status": "running"
  }
  ```

### Change VPS Root Password

- **Endpoint**: `POST /api/v1/vps/<vps_id>/password`
- **Payload**: `{"password": "new_root_secure_pw"}`

### Format and Reinstall OS Template

- **Endpoint**: `POST /api/v1/vps/<vps_id>/reinstall`
- **Payload**:
  ```json
  {
    "os": "ubuntu/24.04",
    "password": "brand_new_root_password"
  }
  ```
  *Supported OS list: `ubuntu/22.04`, `ubuntu/24.04`, `debian/11`, `debian/12`, `centos/9-stream`, `alpine/3.18`*

---

## 📸 Container snapshots (LXC)

### List Snapshots

- **Endpoint**: `GET /api/v1/vps/<vps_id>/snapshots`

### Create Disk Snapshot

- **Endpoint**: `POST /api/v1/vps/<vps_id>/snapshots`
- **Payload**: `{"name": "pre-deployment-backup"}`

### Restore Disk Snapshot

- **Endpoint**: `POST /api/v1/vps/<vps_id>/snapshots/restore`
- **Payload**: `{"name": "pre-deployment-backup"}`

### Delete Snapshot

- **Endpoint**: `DELETE /api/v1/vps/<vps_id>/snapshots/<snapshot_name>`

---

## 🗄️ Container Backups (LXC Tarballs)

### List Backups

- **Endpoint**: `GET /api/v1/vps/<vps_id>/backups`

### Create Complete Backup Export

- **Endpoint**: `POST /api/v1/vps/<vps_id>/backups`

---

## 🛡️ Port Access Firewall

### List Custom Rules

- **Endpoint**: `GET /api/v1/vps/<vps_id>/firewall`

### Add Firewall Rule

- **Endpoint**: `POST /api/v1/vps/<vps_id>/firewall`
- **Payload**:
  ```json
  {
    "protocol": "TCP",  // "TCP", "UDP", "ICMP"
    "port": 80,         // Integer 0-65535
    "action": "ALLOW"   // "ALLOW", "DENY"
  }
  ```

### Delete Firewall Rule

- **Endpoint**: `DELETE /api/v1/vps/<vps_id>/firewall/<rule_id>`

---

## 🛡️ Administrative Control (Admin Only)

### Query Hypervisor / Node Stats

Returns global analytics counts (users, VPS allocations, RAM/CPU dedicated totals).

- **Endpoint**: `GET /api/v1/admin/stats`
- **Response (`200 OK`)**:
  ```json
  {
    "clients": 12,
    "vps_count": 8,
    "allocated_cpu": 16,
    "allocated_ram": 32,
    "total_api_keys": 4,
    "is_mock": false
  }
  ```

### Admin User Management

- **List All Users**: `GET /api/v1/admin/users`
- **Create User Account**: `POST /api/v1/admin/users`
  ```json
  {
    "username": "newclient",
    "email": "newclient@example.com",
    "password": "Password123",
    "role": "client" // "client", "admin"
  }
  ```
- **Update User**: `PUT /api/v1/admin/users/<user_id>`
- **Delete User**: `DELETE /api/v1/admin/users/<user_id>`
- **Suspend/Unsuspend User**: `POST /api/v1/admin/users/<user_id>/suspend`
  ```json
  {
    "suspend": true
  }
  ```

### Admin VPS Management

- **List All System VPS**: `GET /api/v1/admin/vps`
- **Destroy VPS**: `DELETE /api/v1/admin/vps/<vps_id>`
- **Suspend VPS Instance**: `POST /api/v1/admin/vps/<vps_id>/suspend`
  ```json
  {
    "suspend": true
  }
  ```

---

## 🛠️ Errors Handling

API calls that encounter issues return standardized JSON messages with appropriate HTTP status codes:

- `400 Bad Request` — Validation fail (e.g. blank name).
- `401 Unauthorized` — Invalid, missing, or revoked API key.
- `403 Forbidden` — Accessing a VPS not owned by you, or standard client hitting an `/admin` route.
- `404 Not Found` — Resource (VPS, snapshot, rule) does not exist.
- `409 Conflict` — Username or Email already taken during update.
- `500 Server Error` — Hypervisor connection issues or command execution errors.

#### Error payload template:
```json
{
  "error": "forbidden",
  "message": "This endpoint requires one of the following roles: admin."
}
```
