import requests
import json
import time

BASE_URL = "http://127.0.0.1:5000"

def test_lxc_lifecycle():
    # Use a session to persist cookies/session auth
    session = requests.Session()
    
    print("\n--- 1. Login as Seeded Admin ---")
    login_data = {
        "email": "admin@mintyhost.local",
        "password": "admin123"
    }
    resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
    assert resp.status_code == 302, f"Failed to login: {resp.status_code}"
    print("[SUCCESS] Logged in as Admin")

    print("\n--- 2. Fetch Admin Cluster Stats ---")
    resp = session.get(f"{BASE_URL}/api/admin/stats")
    assert resp.status_code == 200
    stats = resp.json()
    print(f"[SUCCESS] Admin stats: {json.dumps(stats, indent=2)}")
    assert stats['is_mock'] is True, "Expected mock mode on Windows"

    print("\n--- 3. Fetch Client Users List ---")
    resp = session.get(f"{BASE_URL}/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    print(f"[SUCCESS] Registered users: {json.dumps(users, indent=2)}")
    client_id = None
    for u in users:
        if u['username'] == 'client1':
            client_id = u['id']
            break
    assert client_id is not None, "Client user client1 not found!"

    print("\n--- 4. Deploy VPS Container for client1 ---")
    # Deploy VPS via deploy-stream endpoint
    deploy_params = {
        "name": "testing",
        "user_id": client_id,
        "os": "debian/11",
        "cpu": 2,
        "ram": 1024,
        "disk": 15,
        "root_password": "supersecurepassword123"
    }
    # Since deploy-stream is SSE, we can read the response stream line-by-line
    resp = session.get(f"{BASE_URL}/api/admin/vps/deploy-stream", params=deploy_params, stream=True)
    assert resp.status_code == 200
    print("SSE Deployment Stream Logs:")
    for line in resp.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            print(f"  {decoded_line}")
            if "SUCCESS" in decoded_line:
                print("[SUCCESS] Deployment completed successfully in stream")

    print("\n--- 5. Verify VPS Table as Admin ---")
    resp = session.get(f"{BASE_URL}/api/admin/vps")
    assert resp.status_code == 200
    vps_list = resp.json()
    print(f"[SUCCESS] Active VPS list: {json.dumps(vps_list, indent=2)}")
    assert len(vps_list) > 0, "No VPS found after deployment"
    vps_id = vps_list[0]['id']
    container_name = vps_list[0]['container_name']

    print("\n--- 6. Log out Admin & Log in as client1 ---")
    session.get(f"{BASE_URL}/logout")
    
    login_data = {
        "email": "client1@mintyhost.local",
        "password": "password123"
    }
    resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
    assert resp.status_code == 302
    print("[SUCCESS] Logged in as client1")

    print("\n--- 7. Get Client VPS List ---")
    resp = session.get(f"{BASE_URL}/api/client/vps")
    assert resp.status_code == 200
    client_vps = resp.json()
    print(f"[SUCCESS] Client VPS: {json.dumps(client_vps, indent=2)}")
    assert len(client_vps) == 1
    assert client_vps[0]['id'] == vps_id

    print("\n--- 8. Fetch VPS Stats ---")
    resp = session.get(f"{BASE_URL}/api/client/vps/{vps_id}/stats")
    assert resp.status_code == 200
    vps_stats = resp.json()
    print(f"[SUCCESS] VPS Stats: {json.dumps(vps_stats, indent=2)}")
    assert vps_stats['status'] == 'running'
    assert vps_stats['ram_limit'] == 1024
    assert vps_stats['cpu'] > 0

    print("\n--- 9. Trigger Power Action: Stop ---")
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/action", json={"action": "stop"})
    assert resp.status_code == 200
    print(f"[SUCCESS] Power stop action: {resp.json()}")

    # Re-fetch stats to check updated status
    resp = session.get(f"{BASE_URL}/api/client/vps/{vps_id}/stats")
    vps_stats = resp.json()
    print(f"[SUCCESS] Status after stop: {vps_stats['status']}")

    print("\n--- 10. Trigger Power Action: Start ---")
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/action", json={"action": "start"})
    assert resp.status_code == 200
    print(f"[SUCCESS] Power start action: {resp.json()}")

    print("\n--- 11. Create & Restore Container Snapshot ---")
    # Create Snapshot
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/snapshots", json={"name": "beforesoftware"})
    assert resp.status_code == 200
    print(f"[SUCCESS] Created snapshot: {resp.json()}")

    # List Snapshots
    resp = session.get(f"{BASE_URL}/api/client/vps/{vps_id}/snapshots")
    assert resp.status_code == 200
    snapshots = resp.json()
    print(f"[SUCCESS] Snapshots list: {json.dumps(snapshots, indent=2)}")
    assert len(snapshots) >= 1
    snap_name = snapshots[0]['name']

    # Restore Snapshot
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/snapshots/restore", json={"name": snap_name})
    assert resp.status_code == 200
    print(f"[SUCCESS] Restored snapshot: {resp.json()}")

    # Delete Snapshot
    resp = session.delete(f"{BASE_URL}/api/client/vps/{vps_id}/snapshots/{snap_name}")
    assert resp.status_code == 200
    print(f"[SUCCESS] Deleted snapshot: {resp.json()}")

    print("\n--- 12. Manage Backups ---")
    # Create Backup
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/backups")
    assert resp.status_code == 200
    print(f"[SUCCESS] Created backup: {resp.json()}")

    # List Backups
    resp = session.get(f"{BASE_URL}/api/client/vps/{vps_id}/backups")
    assert resp.status_code == 200
    backups = resp.json()
    print(f"[SUCCESS] Backups list: {json.dumps(backups, indent=2)}")
    assert len(backups) >= 1

    print("\n--- 13. Manage Firewall Rules ---")
    # Add Rule
    rule_data = {"protocol": "TCP", "port": 80, "action": "ALLOW"}
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/firewall", json=rule_data)
    assert resp.status_code == 200
    print(f"[SUCCESS] Added firewall rule: {resp.json()}")

    # List Rules
    resp = session.get(f"{BASE_URL}/api/client/vps/{vps_id}/firewall")
    assert resp.status_code == 200
    rules = resp.json()
    print(f"[SUCCESS] Firewall rules: {json.dumps(rules, indent=2)}")
    assert len(rules) >= 1
    rule_id = rules[0]['id']

    # Delete Rule
    resp = session.delete(f"{BASE_URL}/api/client/vps/{vps_id}/firewall/{rule_id}")
    assert resp.status_code == 200
    print(f"[SUCCESS] Deleted firewall rule: {resp.json()}")

    print("\n--- 14. Change Password ---")
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/password", json={"root_password": "newrootpassword999"})
    assert resp.status_code == 200
    print(f"[SUCCESS] Changed password: {resp.json()}")

    print("\n--- 15. Reinstall OS ---")
    resp = session.post(f"{BASE_URL}/api/client/vps/{vps_id}/reinstall", json={"os": "ubuntu/22.04", "root_password": "ubuntu_password_999"})
    assert resp.status_code == 200
    print(f"[SUCCESS] Reinstalled OS: {resp.json()}")

    print("\n--- 16. Log out client & Log in as Admin for cleanup ---")
    session.get(f"{BASE_URL}/logout")
    
    login_data = {
        "email": "admin@mintyhost.local",
        "password": "admin123"
    }
    resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
    assert resp.status_code == 302
    print("[SUCCESS] Logged in as Admin")

    print("\n--- 17. Suspend & Unsuspend VPS as Admin ---")
    # Suspend
    resp = session.post(f"{BASE_URL}/api/admin/vps/{vps_id}/suspend", json={"suspend": True})
    assert resp.status_code == 200
    print(f"[SUCCESS] Suspended VPS: {resp.json()}")
    
    # Check status
    resp = session.get(f"{BASE_URL}/api/admin/vps")
    print(f"Status is now: {resp.json()[0]['status']}")

    # Unsuspend
    resp = session.post(f"{BASE_URL}/api/admin/vps/{vps_id}/suspend", json={"suspend": False})
    assert resp.status_code == 200
    print(f"[SUCCESS] Unsuspended VPS: {resp.json()}")

    print("\n--- 18. Audit Logs check ---")
    resp = session.get(f"{BASE_URL}/api/admin/logs")
    assert resp.status_code == 200
    logs = resp.json()
    print(f"[SUCCESS] Audit logs (top 5): {json.dumps(logs[:5], indent=2)}")

    print("\n--- 19. Wipe VPS Container ---")
    resp = session.delete(f"{BASE_URL}/api/admin/vps/{vps_id}")
    assert resp.status_code == 200
    print(f"[SUCCESS] Destroyed VPS: {resp.json()}")

    # Check deleted vps is not in list
    resp = session.get(f"{BASE_URL}/api/admin/vps")
    remaining_ids = [v['id'] for v in resp.json()]
    assert vps_id not in remaining_ids
    print("[SUCCESS] Created VPS is no longer in the active list. Lifecycle testing successful!")

if __name__ == '__main__':
    try:
        test_lxc_lifecycle()
        print("\n==========================================")
        print("ALL VERIFICATION LIFECYCLE TESTS PASSED!")
        print("==========================================")
    except Exception as e:
        print(f"\n[FAILURE] Verification failed: {e}")
        import traceback
        traceback.print_exc()
