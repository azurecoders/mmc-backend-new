from datetime import date, timedelta
import random
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_patient_medical_profile_archive():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        suffix = random_suffix()
        patient_email = f"patient_history_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+193{suffix[:7]}",
                "full_name": f"Cardiac Patient {suffix}",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": patient_email, "password": "Password123!"},
        )
        assert p_login.status_code == 200
        p_headers = {"Authorization": f"Bearer {p_login.json()['access_token']}"}
        patient_id = p_login.json()["user"]["id"]

        # 1. Fetch initial profile (auto-initialized)
        init_resp = await client.get("/api/v1/patients/me/medical-profile", headers=p_headers)
        assert init_resp.status_code == 200
        init_profile = init_resp.json()
        assert init_profile["patient_id"] == patient_id
        assert init_profile["chronic_conditions"] == []

        # 2. Update comprehensive medical history profile
        profile_update_payload = {
            "blood_group": "O+",
            "date_of_birth": "1980-05-15",
            "gender": "MALE",
            "height_cm": 178.5,
            "weight_kg": 84.0,
            "baseline_systolic_bp": 125,
            "baseline_diastolic_bp": 82,
            "chronic_conditions": [
                {
                    "condition": "Coronary Artery Disease (CAD)",
                    "diagnosed_year": 2020,
                    "status": "ACTIVE",
                    "notes": "History of single vessel disease, DES placed in LAD",
                },
                {
                    "condition": "Essential Hypertension",
                    "diagnosed_year": 2018,
                    "status": "ACTIVE",
                    "notes": "Stage 1 HTN on ACE inhibitor",
                },
            ],
            "known_allergies": [
                {
                    "allergen": "Penicillin",
                    "type": "DRUG",
                    "severity": "SEVERE",
                    "reaction": "Anaphylaxis and generalized urticaria",
                },
                {
                    "allergen": "Shellfish",
                    "type": "FOOD",
                    "severity": "MODERATE",
                    "reaction": "Periorbital edema and gastrointestinal cramping",
                },
            ],
            "past_surgeries": [
                {
                    "procedure": "Percutaneous Coronary Intervention (PCI)",
                    "year": 2020,
                    "hospital": "Metropolitan Heart Center",
                    "notes": "Everolimus-eluting stent placed in proximal LAD",
                },
                {
                    "procedure": "Laparoscopic Appendectomy",
                    "year": 2012,
                    "hospital": "General Hospital",
                    "notes": "Uncomplicated recovery",
                },
            ],
            "ongoing_medications": [
                {
                    "medicine_name": "Atorvastatin 20mg",
                    "dosage": "1 tablet at bedtime",
                    "prescribed_for": "Lipid lowering and plaque stabilization",
                },
                {
                    "medicine_name": "Aspirin 75mg",
                    "dosage": "1 tablet after lunch",
                    "prescribed_for": "Antiplatelet therapy",
                },
            ],
            "family_medical_history": [
                {
                    "relation": "Father",
                    "condition": "Fatal Myocardial Infarction at age 52",
                },
                {
                    "relation": "Mother",
                    "condition": "Type 2 Diabetes Mellitus diagnosed age 58",
                },
            ],
            "lifestyle_factors": {
                "smoking_status": "FORMER",
                "alcohol_use": "NONE",
                "exercise_level": "LIGHT",
                "dietary_restrictions": "Strict low-sodium, heart-healthy diet",
            },
            "emergency_contact_name": "Jane Doe",
            "emergency_contact_phone": "+19998887766",
            "emergency_contact_relation": "Spouse",
            "clinical_notes": "Patient carries an emergency nitroglycerin sublingual spray.",
        }

        update_resp = await client.put(
            "/api/v1/patients/me/medical-profile",
            headers=p_headers,
            json=profile_update_payload,
        )
        assert update_resp.status_code == 200
        saved_profile = update_resp.json()
        assert saved_profile["blood_group"] == "O+"
        assert len(saved_profile["chronic_conditions"]) == 2
        assert len(saved_profile["known_allergies"]) == 2
        assert len(saved_profile["past_surgeries"]) == 2
        assert len(saved_profile["ongoing_medications"]) == 2
        assert saved_profile["lifestyle_factors"]["smoking_status"] == "FORMER"

        # 3. Doctor views patient medical history
        dr_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.smith.cardio@hospital.com", "password": "Doctor@123456"},
        )
        dr_headers = {"Authorization": f"Bearer {dr_login.json()['access_token']}"}

        doc_view_resp = await client.get(
            f"/api/v1/patients/{patient_id}/medical-profile",
            headers=dr_headers,
        )
        assert doc_view_resp.status_code == 200
        doc_view = doc_view_resp.json()
        assert doc_view["blood_group"] == "O+"
        assert any(c["condition"] == "Coronary Artery Disease (CAD)" for c in doc_view["chronic_conditions"])


@pytest.mark.asyncio
async def test_patient_self_vitals_logging_and_critical_doctor_alert():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Staff Logins
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
        docs_resp = await client.get("/api/v1/doctors/")
        cardio_doc = next(d for d in docs_resp.json() if "Smith" in d["user"]["full_name"])
        doc_id = cardio_doc["id"]

        # 2. Register Patient & Setup Medical Profile with CAD history
        suffix = random_suffix()
        patient_email = f"patient_vitals_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+192{suffix[:7]}",
                "full_name": f"Vitals Alert Patient {suffix}",
                "password": "Password123!",
            },
        )
        p_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": patient_email, "password": "Password123!"},
        )
        p_headers = {"Authorization": f"Bearer {p_login.json()['access_token']}"}
        patient_id = p_login.json()["user"]["id"]

        # Save profile with CAD
        await client.put(
            "/api/v1/patients/me/medical-profile",
            headers=p_headers,
            json={
                "chronic_conditions": [
                    {"condition": "Coronary Artery Disease", "diagnosed_year": 2021, "status": "ACTIVE"}
                ],
                "ongoing_medications": [
                    {"medicine_name": "Aspirin 75mg", "dosage": "Daily"}
                ],
            },
        )

        # Patient books an appointment with Dr. Sarah Smith so she is their registered consultant
        test_date = str(date.today() + timedelta(days=random.randint(60, 200)))
        apt_resp = await client.post(
            "/api/v1/appointments/book-online",
            headers=p_headers,
            json={
                "doctor_id": doc_id,
                "appointment_date": test_date,
                "slot_time": "14:00",
                "chief_complaint": "Cardiology follow up",
            },
        )
        assert apt_resp.status_code == 201
        apt_id = apt_resp.json()["id"]
        await client.post(f"/api/v1/appointments/{apt_id}/approve", headers=c_headers)

        # 3. Patient logs normal vitals
        normal_vitals_resp = await client.post(
            "/api/v1/vitals/patient-log",
            headers=p_headers,
            json={
                "systolic_bp": 120,
                "diastolic_bp": 80,
                "heart_rate": 72,
                "respiratory_rate": 16,
                "temperature_f": 98.6,
                "spo2": 98.5,
                "consciousness_level": "ALERT",
                "symptoms_notes": "Feeling well today, no symptoms",
            },
        )
        assert normal_vitals_resp.status_code == 201
        normal_vitals = normal_vitals_resp.json()
        assert normal_vitals["mews_score"] == 0
        assert normal_vitals["is_critical"] == False
        assert normal_vitals["triage_level"] == "NORMAL"
        assert normal_vitals["notified_doctor_id"] is None

        # 4. Patient logs CRITICAL vitals with CAD history (Severe Hypertensive Crisis + Chest pain)
        critical_vitals_resp = await client.post(
            "/api/v1/vitals/patient-log",
            headers=p_headers,
            json={
                "systolic_bp": 185,
                "diastolic_bp": 115,
                "heart_rate": 126,
                "respiratory_rate": 26,
                "temperature_f": 99.1,
                "spo2": 91.0,
                "consciousness_level": "ALERT",
                "symptoms_notes": "Crushing retrosternal chest pain and shortness of breath",
            },
        )
        assert critical_vitals_resp.status_code == 201
        critical_vitals = critical_vitals_resp.json()
        assert critical_vitals["is_critical"] == True
        assert critical_vitals["triage_level"] == "CRITICAL_EMERGENCY"
        assert critical_vitals["mews_score"] >= 4
        # Consultant doctor was automatically identified and linked
        assert critical_vitals["notified_doctor_id"] == doc_id
        assert critical_vitals["doctor_notified_at"] is not None
        assert "Smith" in critical_vitals["doctor_name"]
        crit_log_id = critical_vitals["id"]

        # 5. Doctor views their incoming critical alerts
        doc_alerts_resp = await client.get("/api/v1/vitals/doctor/critical-alerts", headers=dr_headers)
        assert doc_alerts_resp.status_code == 200
        doc_alerts = doc_alerts_resp.json()
        matching_alert = next((a for a in doc_alerts if a["vitals_log_id"] == crit_log_id), None)
        assert matching_alert is not None
        assert matching_alert["patient_name"] == f"Vitals Alert Patient {suffix}"
        assert matching_alert["systolic_bp"] == 185
        assert matching_alert["is_critical"] == True
        assert matching_alert["acknowledged"] == False

        # 6. Doctor acknowledges the critical alert
        ack_resp = await client.post(
            f"/api/v1/vitals/alerts/{crit_log_id}/acknowledge",
            headers=dr_headers,
        )
        assert ack_resp.status_code == 200
        assert ack_resp.json()["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_compounder_intake_vitals_and_queue_priority_elevation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Staff Logins
        c_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        c_headers = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        dr_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.patel.general@hospital.com", "password": "Doctor@123456"},
        )
        docs_resp = await client.get("/api/v1/doctors/")
        patel_doc = next(d for d in docs_resp.json() if "Patel" in d["user"]["full_name"])
        doc_id = patel_doc["id"]

        # 2. Patient booking & compounder check-in
        suffix = random_suffix()
        patient_email = f"compounder_intake_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+191{suffix[:7]}",
                "full_name": f"Triage Patient {suffix}",
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
                "slot_time": "10:30",
                "chief_complaint": "Acute febrile illness and rigor",
            },
        )
        apt_id = apt_resp.json()["id"]

        # Compounder approves and checks in as non-priority initially
        await client.post(f"/api/v1/appointments/{apt_id}/approve", headers=c_headers)
        checkin_resp = await client.post(
            "/api/v1/queue/check-in",
            headers=c_headers,
            json={"appointment_id": apt_id, "is_priority": False},
        )
        assert checkin_resp.status_code == 201
        q_entry = checkin_resp.json()
        assert q_entry["is_priority"] == False

        # 3. Compounder records critical vitals during intake triage (High Fever + Severe Tachycardia + Tachypnea)
        intake_resp = await client.post(
            "/api/v1/vitals/compounder-intake",
            headers=c_headers,
            json={
                "appointment_id": apt_id,
                "systolic_bp": 85,  # Hypotension (Septic shock pattern)
                "diastolic_bp": 55,
                "heart_rate": 138,  # Severe tachycardia
                "respiratory_rate": 32,  # Severe tachypnea
                "temperature_f": 103.8,  # High pyrexia
                "spo2": 89.0,  # Hypoxemia
                "consciousness_level": "VOICE",  # Drowsy
                "symptoms_notes": "Patient confused and shivering vigorously, suspected severe sepsis",
            },
        )
        assert intake_resp.status_code == 201
        intake_vitals = intake_resp.json()
        assert intake_vitals["is_critical"] == True
        assert intake_vitals["triage_level"] == "CRITICAL_EMERGENCY"
        assert intake_vitals["mews_score"] >= 6

        # 4. Verify the patient's queue entry has been escalated to is_priority == True!
        p_status_resp = await client.get(f"/api/v1/queue/patient-status/{apt_id}", headers=p_headers)
        assert p_status_resp.status_code == 200
        p_status = p_status_resp.json()
        assert p_status["is_priority"] == True
