from datetime import date, timedelta
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_departments_and_doctors_directory():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Fetch departments
        dept_resp = await client.get("/api/v1/departments/")
        assert dept_resp.status_code == 200
        depts = dept_resp.json()
        assert len(depts) >= 4
        assert any(d["code"] == "CARDIOLOGY" for d in depts)
        assert any(d["code"] == "GENERAL_MEDICINE" for d in depts)

        # 2. Fetch doctors directory
        doc_resp = await client.get("/api/v1/doctors/")
        assert doc_resp.status_code == 200
        docs = doc_resp.json()
        assert len(docs) >= 4
        assert any("Cardiologist" in d["specialization"] for d in docs)
        assert any(d["consultation_fee"] > 0 for d in docs)

@pytest.mark.asyncio
async def test_ai_doctor_recommendation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register a patient to authenticate
        suffix = random_suffix()
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"ai_patient_{suffix}@example.com",
                "phone": f"+188{suffix[:7]}",
                "full_name": f"AI Triage Patient {suffix}",
                "password": "Password123!",
            },
        )
        assert reg_resp.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": f"ai_patient_{suffix}@example.com",
                "password": "Password123!",
            },
        )
        token = login_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Case 1: Cardiovascular symptoms
        cardio_req = {
            "symptoms": "Heavy pressure in the chest and breathlessness while climbing stairs for 3 days",
            "duration": "3 days",
            "severity": "MODERATE",
        }
        cardio_resp = await client.post(
            "/api/v1/appointments/recommend-doctors",
            headers=auth_headers,
            json=cardio_req,
        )
        assert cardio_resp.status_code == 200
        cardio_data = cardio_resp.json()
        assert cardio_data["recommended_department"] == "CARDIOLOGY"
        assert len(cardio_data["recommended_doctors"]) > 0
        top_doc = cardio_data["recommended_doctors"][0]
        assert "Cardio" in top_doc["doctor"]["specialization"]
        assert top_doc["doctor"]["consultation_fee"] > 0
        assert top_doc["match_score"] > 0.5

        # Case 2: Orthopedic symptoms
        ortho_req = {
            "symptoms": "Sharp knee pain and joint swelling after falling down the stairs",
            "duration": "1 day",
            "severity": "SEVERE",
        }
        ortho_resp = await client.post(
            "/api/v1/appointments/recommend-doctors",
            headers=auth_headers,
            json=ortho_req,
        )
        assert ortho_resp.status_code == 200
        ortho_data = ortho_resp.json()
        assert ortho_data["recommended_department"] == "ORTHOPEDICS"
        assert len(ortho_data["recommended_doctors"]) > 0
        top_ortho = ortho_data["recommended_doctors"][0]
        assert "Ortho" in top_ortho["doctor"]["specialization"]

@pytest.mark.asyncio
async def test_online_appointment_booking_and_token_sequencing():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Get cardiologist ID
        docs_resp = await client.get("/api/v1/doctors/")
        docs = docs_resp.json()
        cardio_doc = next(d for d in docs if "Cardio" in d["specialization"])
        doc_id = cardio_doc["id"]

        booking_date = str(date.today() + timedelta(days=2))

        # Register Patient 1
        suffix1 = random_suffix()
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"patient_seq1_{suffix1}@example.com",
                "phone": f"+177{suffix1[:7]}",
                "full_name": "Seq Patient 1",
                "password": "Password123!",
            },
        )
        login1 = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": f"patient_seq1_{suffix1}@example.com", "password": "Password123!"},
        )
        token1 = login1.json()["access_token"]

        # Patient 1 books appointment
        book1_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers={"Authorization": f"Bearer {token1}"},
            json={
                "doctor_id": doc_id,
                "appointment_date": booking_date,
                "slot_time": "10:00",
                "chief_complaint": "Chest discomfort and high blood pressure",
                "symptom_duration": "2 days",
                "severity": "MODERATE",
                "ai_recommended_department": "CARDIOLOGY",
            },
        )
        assert book1_resp.status_code == 201
        book1_data = book1_resp.json()
        initial_token = book1_data["token_number"]
        assert initial_token >= 1
        assert book1_data["status"] == "PENDING_APPROVAL"
        assert book1_data["booking_type"] == "ONLINE"

        # Register Patient 2
        suffix2 = random_suffix()
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"patient_seq2_{suffix2}@example.com",
                "phone": f"+178{suffix2[:7]}",
                "full_name": "Seq Patient 2",
                "password": "Password123!",
            },
        )
        login2 = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": f"patient_seq2_{suffix2}@example.com", "password": "Password123!"},
        )
        token2 = login2.json()["access_token"]

        # Patient 2 books with same doctor on same date -> should get exactly initial_token + 1!
        book2_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers={"Authorization": f"Bearer {token2}"},
            json={
                "doctor_id": doc_id,
                "appointment_date": booking_date,
                "slot_time": "10:30",
                "chief_complaint": "Follow up consultation for heart condition",
                "symptom_duration": "1 week",
                "severity": "MILD",
            },
        )
        assert book2_resp.status_code == 201
        book2_data = book2_resp.json()
        assert book2_data["token_number"] == initial_token + 1
        assert book2_data["status"] == "PENDING_APPROVAL"

@pytest.mark.asyncio
async def test_compounder_verification_and_approval_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login as Compounder
        compounder_login = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": "compounder@hospital.com",
                "password": "Compounder@123",
            },
        )
        assert compounder_login.status_code == 200
        compounder_token = compounder_login.json()["access_token"]
        compounder_headers = {"Authorization": f"Bearer {compounder_token}"}

        # 2. Patient books an online appointment
        docs_resp = await client.get("/api/v1/doctors/")
        doc_id = docs_resp.json()[0]["id"]
        suffix = random_suffix()
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"verify_patient_{suffix}@example.com",
                "phone": f"+166{suffix[:7]}",
                "full_name": "Verification Patient",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": f"verify_patient_{suffix}@example.com", "password": "Password123!"},
        )
        p_token = p_login.json()["access_token"]

        booking_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers={"Authorization": f"Bearer {p_token}"},
            json={
                "doctor_id": doc_id,
                "appointment_date": str(date.today() + timedelta(days=3)),
                "slot_time": "11:00",
                "chief_complaint": "Severe flu symptoms and fever",
                "symptom_duration": "4 days",
                "severity": "MODERATE",
            },
        )
        assert booking_resp.status_code == 201
        apt_id = booking_resp.json()["id"]

        # 3. Compounder checks pending approvals
        pending_resp = await client.get("/api/v1/appointments/pending-approvals", headers=compounder_headers)
        assert pending_resp.status_code == 200
        pending_list = pending_resp.json()
        assert any(a["id"] == apt_id for a in pending_list)

        # 4. Compounder approves appointment
        approve_resp = await client.post(
            f"/api/v1/appointments/{apt_id}/approve",
            headers=compounder_headers,
            json={"notes": "Patient insurance verified, approved for consultation."},
        )
        assert approve_resp.status_code == 200
        approved_data = approve_resp.json()
        assert approved_data["status"] == "APPROVED"
        assert approved_data["verified_by_compounder_id"] is not None
        assert approved_data["verified_at"] is not None

@pytest.mark.asyncio
async def test_compounder_walkin_booking_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Login as Compounder
        compounder_login = await client.post(
            "/api/v1/auth/login",
            json={
                "username_or_email": "compounder@hospital.com",
                "password": "Compounder@123",
            },
        )
        compounder_token = compounder_login.json()["access_token"]
        compounder_headers = {"Authorization": f"Bearer {compounder_token}"}

        docs_resp = await client.get("/api/v1/doctors/")
        doc_id = docs_resp.json()[0]["id"]

        # Walk-in registration: Patient arrives in person with no prior account
        suffix = random_suffix()
        walkin_req = {
            "walkin_patient": {
                "full_name": f"Walkin Dave {suffix}",
                "phone": f"+155{suffix[:7]}",
                "email": f"dave_walkin_{suffix}@example.com",
            },
            "doctor_id": doc_id,
            "chief_complaint": "Acute abdominal pain and nausea",
            "symptom_duration": "6 hours",
            "severity": "SEVERE",
        }

        walkin_resp = await client.post(
            "/api/v1/appointments/book-walkin",
            headers=compounder_headers,
            json=walkin_req,
        )
        assert walkin_resp.status_code == 201
        walkin_data = walkin_resp.json()
        assert walkin_data["booking_type"] == "WALK_IN"
        assert walkin_data["status"] == "APPROVED"
        assert walkin_data["token_number"] >= 1
        assert walkin_data["patient"]["full_name"] == f"Walkin Dave {suffix}"
        assert walkin_data["verified_by_compounder_id"] is not None

@pytest.mark.asyncio
async def test_compounder_reject_appointment():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        compounder_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        compounder_headers = {"Authorization": f"Bearer {compounder_login.json()['access_token']}"}

        docs_resp = await client.get("/api/v1/doctors/")
        doc_id = docs_resp.json()[0]["id"]
        suffix = random_suffix()

        # Patient books
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"reject_p_{suffix}@example.com",
                "phone": f"+144{suffix[:7]}",
                "full_name": "Reject Tester",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": f"reject_p_{suffix}@example.com", "password": "Password123!"},
        )
        booking_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers={"Authorization": f"Bearer {p_login.json()['access_token']}"},
            json={
                "doctor_id": doc_id,
                "appointment_date": str(date.today() + timedelta(days=5)),
                "slot_time": "14:00",
                "chief_complaint": "Minor headache",
            },
        )
        apt_id = booking_resp.json()["id"]

        # Compounder rejects
        reject_resp = await client.post(
            f"/api/v1/appointments/{apt_id}/reject",
            headers=compounder_headers,
            json={"rejection_reason": "Doctor has emergency surgeries scheduled during this slot."},
        )
        assert reject_resp.status_code == 200
        rejected_data = reject_resp.json()
        assert rejected_data["status"] == "REJECTED"
        assert rejected_data["rejection_reason"] == "Doctor has emergency surgeries scheduled during this slot."
