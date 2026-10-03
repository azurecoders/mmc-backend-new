import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

@pytest.mark.asyncio
async def test_superadmin_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Login with seeded superadmin
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": "admin@hospital.com",
                "password": "Admin@123456",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "admin@hospital.com"
        assert any(r["code"] == "SUPER_ADMIN" for r in data["user"]["roles"])
        assert "*" in data["user"]["permissions"]

@pytest.mark.asyncio
async def test_patient_registration_and_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        suffix = random_suffix()
        email = f"patient_{suffix}@example.com"
        phone = f"+199{suffix[:7]}"

        # 1. Register a new patient
        register_payload = {
            "email": email,
            "phone": phone,
            "full_name": f"Patient {suffix}",
            "password": "PatientPassword123",
        }
        reg_response = await client.post("/api/v1/auth/register", json=register_payload)
        assert reg_response.status_code == 201
        reg_data = reg_response.json()
        assert reg_data["email"] == email
        assert any(r["code"] == "PATIENT" for r in reg_data["roles"])
        assert "appointments:create" in reg_data["permissions"]

        # 2. Login with email
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": email,
                "password": "PatientPassword123",
            },
        )
        assert login_response.status_code == 200
        login_data = login_response.json()
        patient_token = login_data["access_token"]

        # 3. Login with phone
        phone_login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": phone,
                "password": "PatientPassword123",
            },
        )
        assert phone_login_response.status_code == 200

        # 4. Patient attempts to access roles management endpoint (should be blocked with 403 Forbidden)
        forbidden_resp = await client.get(
            "/api/v1/roles/",
            headers={"Authorization": f"Bearer {patient_token}"},
        )
        assert forbidden_resp.status_code == 403
        assert "Missing required permission" in forbidden_resp.json()["detail"]

@pytest.mark.asyncio
async def test_create_staff_and_dynamic_roles_with_inheritance():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        suffix = random_suffix()

        # 1. Login as Super Admin
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": "admin@hospital.com",
                "password": "Admin@123456",
            },
        )
        admin_token = admin_login.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Fetch DOCTOR role to get its ID
        roles_resp = await client.get("/api/v1/roles/", headers=auth_headers)
        assert roles_resp.status_code == 200
        roles = roles_resp.json()
        doctor_role = next(r for r in roles if r["code"] == "DOCTOR")
        doctor_role_id = doctor_role["id"]

        # 3. Create a brand new custom permission dynamically
        new_perm_code = f"cardiology:perform_ecg_{suffix}"
        new_perm_resp = await client.post(
            "/api/v1/permissions/",
            headers=auth_headers,
            json={
                "code": new_perm_code,
                "name": "Perform ECG",
                "module": "CARDIOLOGY",
                "description": "Ability to order and evaluate electrocardiograms",
            },
        )
        assert new_perm_resp.status_code == 201

        # 4. Create a dynamic sub-role: CARDIOLOGIST with parent = DOCTOR
        # This proves the system is 100% dynamic without modifying code!
        new_role_code = f"CARDIOLOGIST_{suffix.upper()}"
        new_role_resp = await client.post(
            "/api/v1/roles/",
            headers=auth_headers,
            json={
                "code": new_role_code,
                "name": f"Cardiologist Specialist {suffix}",
                "description": "Senior Heart Specialist inheriting all Doctor privileges",
                "parent_role_id": doctor_role_id,
                "permission_codes": [new_perm_code],
            },
        )
        assert new_role_resp.status_code == 201
        cardiologist_role = new_role_resp.json()
        
        # Verify that the sub-role effectively inherits DOCTOR permissions + has its own
        effective_codes = cardiologist_role["effective_permission_codes"]
        assert new_perm_code in effective_codes
        assert "consultations:create" in effective_codes
        assert "prescriptions:create" in effective_codes

        # 5. Create a staff member with this new dynamic sub-role
        doctor_email = f"dr.heart_{suffix}@hospital.com"
        staff_resp = await client.post(
            "/api/v1/users/",
            headers=auth_headers,
            json={
                "email": doctor_email,
                "phone": f"+155{suffix[:7]}",
                "full_name": f"Dr. Heart Specialist {suffix}",
                "password": "SecureDoctor123",
                "role_codes": [new_role_code],
            },
        )
        assert staff_resp.status_code == 201
        staff_data = staff_resp.json()
        assert any(r["code"] == new_role_code for r in staff_data["roles"])
        assert new_perm_code in staff_data["permissions"]
        assert "consultations:create" in staff_data["permissions"]

        # 6. Login as the newly created Cardiologist
        dr_login = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": doctor_email,
                "password": "SecureDoctor123",
            },
        )
        assert dr_login.status_code == 200
        dr_token = dr_login.json()["access_token"]

        # 7. Check /auth/me for this doctor
        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {dr_token}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert new_perm_code in me_data["permissions"]
        assert "consultations:create" in me_data["permissions"]

@pytest.mark.asyncio
async def test_refresh_token_and_logout():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        suffix = random_suffix()
        email = f"session_{suffix}@example.com"
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "phone": f"+123{suffix[:7]}",
                "full_name": f"Session Tester {suffix}",
                "password": "Password123!",
            },
        )
        assert reg.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": email,
                "password": "Password123!",
            },
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        old_access = data["access_token"]
        old_refresh = data["refresh_token"]

        # Refresh token exchange
        ref_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert ref_resp.status_code == 200
        ref_data = ref_resp.json()
        new_access = ref_data["access_token"]
        new_refresh = ref_data["refresh_token"]
        assert new_access != old_access
        assert new_refresh != old_refresh

        # Using old refresh token should now fail (token rotation)
        bad_ref = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert bad_ref.status_code == 401

        # Logout with active refresh token
        logout_resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_access}"},
            json={"refresh_token": new_refresh},
        )
        assert logout_resp.status_code == 200

        # Attempting refresh after logout fails
        after_logout_ref = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        assert after_logout_ref.status_code == 401
