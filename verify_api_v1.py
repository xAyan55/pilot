import requests
import json

BASE_URL = "http://127.0.0.1:5000"

def test_api_v1():
    session = requests.Session()

    # Login as Admin via session to generate an API key
    print("\n--- 1. Login as Admin via Session ---")
    login_data = {"email": "admin@pilotpanel.local", "password": "admin123"}
    resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
    assert resp.status_code == 302
    print("[SUCCESS] Admin Session Established.")

    # Generate API key via Session POST
    print("\n--- 2. Generate API Key via Session ---")
    resp = session.post(f"{BASE_URL}/api/keys", json={"name": "Integration Test Key"})
    assert resp.status_code == 201
    key_data = resp.json()
    api_key = key_data['key']['key']
    print(f"[SUCCESS] Generated API Key: {api_key[:8]}...{api_key[-4:]}")

    # Try accessing with no auth header (should return 401)
    print("\n--- 3. Verify Authentication Gate (No Token) ---")
    resp = requests.get(f"{BASE_URL}/api/v1/profile")
    assert resp.status_code == 401
    print("[SUCCESS] Blocked unauthorized request.")

    # Try accessing with invalid token
    print("\n--- 4. Verify Authentication Gate (Invalid Token) ---")
    resp = requests.get(f"{BASE_URL}/api/v1/profile", headers={"Authorization": "Bearer invalid_key_here"})
    assert resp.status_code == 401
    print("[SUCCESS] Blocked invalid token.")

    # Access profile with valid API key
    print("\n--- 5. Get User Profile via API v1 ---")
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{BASE_URL}/api/v1/profile", headers=headers)
    assert resp.status_code == 200
    profile = resp.json()
    print(f"[SUCCESS] Profile info: {json.dumps(profile, indent=2)}")
    assert profile['username'] == 'admin'

    # Get settings public (no auth)
    print("\n--- 6. Get Public Settings (Unauthenticated) ---")
    resp = requests.get(f"{BASE_URL}/api/v1/settings/public")
    assert resp.status_code == 200
    settings = resp.json()
    print(f"[SUCCESS] Public settings: {json.dumps(settings, indent=2)}")
    assert 'site_name' in settings

    # List all keys owned by user
    print("\n--- 7. List Active Keys via API ---")
    resp = requests.get(f"{BASE_URL}/api/v1/keys", headers=headers)
    assert resp.status_code == 200
    keys = resp.json()
    print(f"[SUCCESS] Keys found: {len(keys)}")
    assert len(keys) >= 1

    # Create another key via API v1
    print("\n--- 8. Create Sub-key via API v1 ---")
    resp = requests.post(f"{BASE_URL}/api/v1/keys", headers=headers, json={"name": "Sub-key 01"})
    assert resp.status_code == 201
    sub_key_data = resp.json()
    sub_key_id = sub_key_data['key']['id']
    print(f"[SUCCESS] Created sub-key ID: {sub_key_id}")

    # Revoke key via API v1
    print("\n--- 9. Revoke Sub-key via API v1 ---")
    resp = requests.delete(f"{BASE_URL}/api/v1/keys/{sub_key_id}", headers=headers)
    assert resp.status_code == 200
    print("[SUCCESS] Revoked sub-key successfully.")

    # List all system VPS via Admin API
    print("\n--- 10. List VPS List via Admin API ---")
    resp = requests.get(f"{BASE_URL}/api/v1/vps", headers=headers)
    assert resp.status_code == 200
    vps_list = resp.json()
    print(f"[SUCCESS] Total VPS in system: {len(vps_list)}")

    # Verify user credentials via Admin API
    print("\n--- 11. Verify User Credentials via Admin API ---")
    resp = requests.post(f"{BASE_URL}/api/v1/admin/users/verify", headers=headers, json={
        "username": "admin",
        "password": "admin123"
    })
    assert resp.status_code == 200
    assert resp.json().get("valid") is True
    print("[SUCCESS] Credentials verified successfully.")

    # Create User via Admin API with discord_user_id
    print("\n--- 12. Create User via Admin API with Discord notification ---")
    import random
    rand_suffix = random.randint(1000, 9999)
    resp = requests.post(f"{BASE_URL}/api/v1/admin/users", headers=headers, json={
        "username": f"apitestuser{rand_suffix}",
        "email": f"apiuser{rand_suffix}@pilotpanel.local",
        "password": "strongpassword123",
        "role": "client",
        "discord_user_id": "123456789012345678"
    })
    assert resp.status_code == 201
    created_user_id = resp.json()['id']
    print(f"[SUCCESS] Created user with ID: {created_user_id}")

    # Deploy VPS via Admin API with discord_user_id
    print("\n--- 13. Deploy VPS via Admin API with Discord notification ---")
    resp = requests.post(f"{BASE_URL}/api/v1/admin/vps", headers=headers, json={
        "name": "apitestvps",
        "user_id": created_user_id,
        "os": "alpine/3.18",
        "cpu": 1,
        "ram": 512,
        "disk": 10,
        "root_password": "securesshpassword123",
        "discord_user_id": "123456789012345678"
    })
    assert resp.status_code == 201
    deployed = resp.json()
    vps_id = deployed['vps']['id']
    print(f"[SUCCESS] Deployed VPS ID: {vps_id}")

    # Delete VPS via Admin API
    print("\n--- 14. Destroy VPS via Admin API ---")
    resp = requests.delete(f"{BASE_URL}/api/v1/admin/vps/{vps_id}", headers=headers)
    assert resp.status_code == 200
    print("[SUCCESS] Destroyed VPS successfully.")

    # Cleanup the test keys we generated to keep DB tidy
    print("\n--- 15. Clean Up Test Key ---")
    key_id_to_delete = key_data['key']['id']
    resp = session.delete(f"{BASE_URL}/api/keys/{key_id_to_delete}")
    assert resp.status_code == 200
    print("[SUCCESS] Cleaned up integration test credentials.")

    print("\n==========================================")
    print("ALL REST API V1 INTEGRATION TESTS PASSED!")
    print("==========================================")

if __name__ == "__main__":
    test_api_v1()
