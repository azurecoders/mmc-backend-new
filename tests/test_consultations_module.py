from datetime import date, timedelta
import random
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_lab_catalog():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Fetch lab catalog
        catalog_resp = await client.get("/api/v1/lab/catalog")
        assert catalog_resp.status_code == 200
        catalog = catalog_resp.json()
        assert len(catalog) >= 5
        codes = [t["code"] for t in catalog]
        assert "CBC" in codes
        assert "XRAY_CHEST" in codes
        assert "LIPID_PROFILE" in codes

        # 2. Lab assistant adds a new test
        lab_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "lab@hospital.com", "password": "Lab@123456"},
        )
        assert lab_login.status_code == 200
        lab_headers = {"Authorization": f"Bearer {lab_login.json()['access_token']}"}

        suffix = random_suffix()
        new_test_resp = await client.post(
            "/api/v1/lab/catalog",
            headers=lab_headers,
            json={
                "name": f"Troponin-I Quantitative {suffix}",
                "code": f"TROP_I_{suffix.upper()}",
                "category": "CARDIOLOGY",
                "description": "High sensitivity cardiac troponin for myocardial infarction",
                "standard_turnaround_hours": 1,
            },
        )
        assert new_test_resp.status_code == 201
        assert new_test_resp.json()["code"] == f"TROP_I_{suffix.upper()}"

@pytest.mark.asyncio
async def test_doctor_consultation_prescriptions_and_lab_orders():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Logins
        c_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        c_headers = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        dr_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.smith.cardio@hospital.com", "password": "Doctor@123456"},
        )
        dr_headers = {"Authorization": f"Bearer {dr_login.json()['access_token']}"}

        # 2. Get Doctor and Lab test IDs
        docs_resp = await client.get("/api/v1/doctors/")
        cardio_doc = next(d for d in docs_resp.json() if "Cardio" in d["specialization"])
        doc_id = cardio_doc["id"]

        catalog_resp = await client.get("/api/v1/lab/catalog")
        catalog = catalog_resp.json()
        ecg_test = next(t for t in catalog if t["code"] == "ECG")
        lipid_test = next(t for t in catalog if t["code"] == "LIPID_PROFILE")

        # 3. Patient books appointment and compounder checks in
        suffix = random_suffix()
        patient_email = f"patient_consult_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+196{suffix[:7]}",
                "full_name": f"Heart Patient {suffix}",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": patient_email, "password": "Password123!"},
        )
        p_token = p_login.json()["access_token"]
        p_headers = {"Authorization": f"Bearer {p_token}"}
        patient_id = p_login.json()["user"]["id"]

        test_date = str(date.today() + timedelta(days=random.randint(60, 200)))
        apt_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers=p_headers,
            json={
                "doctor_id": doc_id,
                "appointment_date": test_date,
                "slot_time": "10:00",
                "chief_complaint": "Retrosternal chest burning and tightness during exercise",
                "symptom_duration": "1 week",
                "severity": "MODERATE",
            },
        )
        assert apt_resp.status_code == 201
        apt_id = apt_resp.json()["id"]

        # Compounder approves and checks in
        await client.post(f"/api/v1/appointments/{apt_id}/approve", headers=c_headers)
        checkin_resp = await client.post(
            "/api/v1/queue/check-in",
            headers=c_headers,
            json={"appointment_id": apt_id, "is_priority": False},
        )
        q_id = checkin_resp.json()["id"]

        # Call patient
        await client.post("/api/v1/queue/call-patient", headers=c_headers, json={"queue_entry_id": q_id})

        # 4. Doctor submits consultation with clinical notes, 2 prescriptions, and 2 lab tests
        consult_payload = {
            "appointment_id": apt_id,
            "chief_complaint": "Exertional angina and retrosternal tightness",
            "symptoms": "Tightness radiating to left arm when walking uphill. Relieved by resting.",
            "diagnosis": "Stable Angina Pectoris / Coronary Artery Disease Evaluation",
            "clinical_notes": "S1 S2 regular, no audible murmurs. BP 138/86 mmHg, Pulse 76 bpm. Advised lifestyle modifications.",
            "special_instructions": "Maintain low-sodium, heart-healthy Mediterranean diet. Avoid heavy lifting.",
            "highlights": "RED FLAG: If chest pain lasts more than 15 minutes or radiates to jaw, proceed immediately to the Emergency Room.",
            "follow_up_date": str(date.today() + timedelta(days=14)),
            "prescriptions": [
                {
                    "medicine_name": "Atorvastatin 20mg",
                    "dosage": "1 tablet",
                    "frequency": "Once daily at night",
                    "duration": "30 days",
                    "instructions": "Take at bedtime with water",
                },
                {
                    "medicine_name": "Aspirin 75mg (Ecosprin)",
                    "dosage": "1 tablet",
                    "frequency": "Once daily after lunch",
                    "duration": "30 days",
                    "instructions": "Must be taken after meals to prevent gastric irritation",
                },
            ],
            "lab_orders": [
                {
                    "test_id": ecg_test["id"],
                    "instructions": "Baseline 12-lead resting ECG",
                    "urgency": "URGENT",
                },
                {
                    "test_id": lipid_test["id"],
                    "instructions": "12 hours strict fasting required prior to blood sample collection",
                    "urgency": "ROUTINE",
                },
            ],
            "finalize": True,
        }

        consult_resp = await client.post(
            "/api/v1/consultations/",
            headers=dr_headers,
            json=consult_payload,
        )
        assert consult_resp.status_code == 201
        c_data = consult_resp.json()
        assert c_data["diagnosis"] == "Stable Angina Pectoris / Coronary Artery Disease Evaluation"
        assert c_data["is_finalized"] == True
        assert len(c_data["prescription_items"]) == 2
        assert len(c_data["lab_orders"]) == 2
        consult_id = c_data["id"]

        # 5. Patient views consultation & prescriptions via /consultations/appointment/{apt_id}
        patient_view_resp = await client.get(
            f"/api/v1/consultations/appointment/{apt_id}",
            headers=p_headers,
        )
        assert patient_view_resp.status_code == 200
        p_view = patient_view_resp.json()
        assert p_view["diagnosis"] == c_data["diagnosis"]
        assert len(p_view["prescription_items"]) == 2
        assert any(item["medicine_name"] == "Atorvastatin 20mg" for item in p_view["prescription_items"])
        assert any("Emergency Room" in p_view["highlights"] for _ in [1])

        # 6. Lab assistant views ordered tests
        lab_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "lab@hospital.com", "password": "Lab@123456"},
        )
        lab_headers = {"Authorization": f"Bearer {lab_login.json()['access_token']}"}
        orders_resp = await client.get("/api/v1/lab/orders", headers=lab_headers)
        assert orders_resp.status_code == 200
        all_orders = orders_resp.json()
        assert any(o["consultation_id"] == consult_id for o in all_orders)

        # 8. Pharmacist checks prescription queue
        pharm_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "pharmacist@hospital.com", "password": "Pharmacist@123"},
        )
        assert pharm_login.status_code == 200
        pharm_headers = {"Authorization": f"Bearer {pharm_login.json()['access_token']}"}
        pharm_queue_resp = await client.get("/api/v1/pharmacy/prescriptions", headers=pharm_headers)
        assert pharm_queue_resp.status_code == 200
        pharma_queue = pharm_queue_resp.json()
        assert any(q["consultation_id"] == consult_id for q in pharma_queue)
        target_q = next(q for q in pharma_queue if q["consultation_id"] == consult_id)
        assert len(target_q["items"]) == 2

@pytest.mark.asyncio
async def test_doctor_consultation_with_prescription_items_frontend_payload():
    """Verify that consultation accepts prescription_items (the exact payload key sent by the frontend)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login as compounder and doctor
        c_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        c_headers = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        dr_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.smith.cardio@hospital.com", "password": "Doctor@123456"},
        )
        dr_headers = {"Authorization": f"Bearer {dr_login.json()['access_token']}"}

        # 2. Get Doctor ID
        docs_resp = await client.get("/api/v1/doctors/")
        doc_id = docs_resp.json()[0]["id"]

        # 3. Patient register & book
        suffix = random_suffix()
        patient_email = f"patient_rx_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+195{suffix[:7]}",
                "full_name": f"Prescription Patient {suffix}",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": patient_email, "password": "Password123!"},
        )
        p_headers = {"Authorization": f"Bearer {p_login.json()['access_token']}"}

        test_date = str(date.today() + timedelta(days=random.randint(60, 200)))
        apt_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers=p_headers,
            json={
                "doctor_id": doc_id,
                "appointment_date": test_date,
                "slot_time": "11:00",
                "chief_complaint": "Persistent headache",
            },
        )
        apt_id = apt_resp.json()["id"]

        # Compounder verifies
        await client.post(f"/api/v1/appointments/{apt_id}/verify-and-approve", headers=c_headers)

        # 4. Doctor submits using `prescription_items` (the key used by frontend UI)
        consult_payload = {
            "appointment_id": apt_id,
            "chief_complaint": "Persistent headache and fever",
            "diagnosis": "Tension Headache & Mild Viral Pyrexia",
            "clinical_notes": "Vitals normal. Advised paracetamol and hydration.",
            "prescription_items": [
                {
                    "medicine_name": "Paracetamol 500mg",
                    "dosage": "1 tablet",
                    "frequency": "Thrice daily after meals",
                    "duration": "3 days",
                    "instructions": "Take after meals with water",
                },
                {
                    "medicine_name": "Cetirizine 10mg",
                    "dosage": "1 tablet",
                    "frequency": "Once daily at bedtime",
                    "duration": "5 days",
                    "instructions": "Take at night",
                },
            ],
            "finalize": True,
        }

        consult_resp = await client.post(
            "/api/v1/consultations/",
            headers=dr_headers,
            json=consult_payload,
        )
        assert consult_resp.status_code == 201
        c_data = consult_resp.json()
        assert len(c_data["prescription_items"]) == 2
        assert any(item["medicine_name"] == "Paracetamol 500mg" for item in c_data["prescription_items"])

        # 5. Verify pharmacy sees the new prescription in queue
        pharm_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "pharmacist@hospital.com", "password": "Pharmacist@123"},
        )
        pharm_headers = {"Authorization": f"Bearer {pharm_login.json()['access_token']}"}
        pharm_queue_resp = await client.get("/api/v1/pharmacy/prescriptions", headers=pharm_headers)
        assert pharm_queue_resp.status_code == 200
        target = next((q for q in pharm_queue_resp.json() if q["consultation_id"] == c_data["id"]), None)
        assert target is not None
        assert len(target["items"]) == 2

        # 6. Patient requests AI explanation of prescription
        explain_resp = await client.post(
            f"/api/v1/consultations/{c_data['id']}/explain-prescription",
            headers=p_headers,
        )
        assert explain_resp.status_code == 200
        explanation = explain_resp.json()
        assert explanation["consultation_id"] == c_data["id"]
        assert len(explanation["medicines"]) >= 1
        assert "Paracetamol" in explanation["medicines"][0]["medicine_name"]
        assert explanation["summary"] is not None
        assert isinstance(explanation["lifestyle_and_diet_recommendations"], list)
        assert isinstance(explanation["warning_signs_to_watch"], list)

