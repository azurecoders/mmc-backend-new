from datetime import date, timedelta
import random
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_pharmacy_inventory_management():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login as Pharmacist
        pharm_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "pharmacist@hospital.com", "password": "Pharmacist@123"},
        )
        assert pharm_login.status_code == 200
        pharm_headers = {"Authorization": f"Bearer {pharm_login.json()['access_token']}"}

        # 2. View Inventory
        inv_resp = await client.get("/api/v1/pharmacy/inventory", headers=pharm_headers)
        assert inv_resp.status_code == 200
        inventory = inv_resp.json()
        assert len(inventory) >= 6
        med_names = [m["name"] for m in inventory]
        assert "Atorvastatin 20mg" in med_names
        assert "Amoxicillin 500mg" in med_names

        # Filter by category
        cardio_resp = await client.get(
            "/api/v1/pharmacy/inventory?category=CARDIOVASCULAR",
            headers=pharm_headers,
        )
        assert cardio_resp.status_code == 200
        for item in cardio_resp.json():
            assert item["category"] == "CARDIOVASCULAR"

        # 3. Add a new drug
        suffix = random_suffix()
        new_drug_name = f"Ciprofloxacin {suffix} 500mg"
        add_resp = await client.post(
            "/api/v1/pharmacy/inventory",
            headers=pharm_headers,
            json={
                "name": new_drug_name,
                "generic_name": "Ciprofloxacin Hydrochloride",
                "category": "ANTIBIOTIC",
                "dosage_form": "TABLET",
                "unit_price": 1.75,
                "stock_quantity": 120,
                "reorder_level": 25,
            },
        )
        assert add_resp.status_code == 201
        created_drug = add_resp.json()
        assert created_drug["name"] == new_drug_name
        assert created_drug["stock_quantity"] == 120
        drug_id = created_drug["id"]

        # Duplicate drug name check
        dup_resp = await client.post(
            "/api/v1/pharmacy/inventory",
            headers=pharm_headers,
            json={
                "name": new_drug_name,
                "generic_name": "Ciprofloxacin",
                "category": "ANTIBIOTIC",
                "dosage_form": "TABLET",
                "unit_price": 2.00,
                "stock_quantity": 50,
                "reorder_level": 10,
            },
        )
        assert dup_resp.status_code == 400
        assert "already exists" in dup_resp.json()["detail"]

        # 4. Update stock quantity & price
        update_resp = await client.put(
            f"/api/v1/pharmacy/inventory/{drug_id}",
            headers=pharm_headers,
            json={
                "stock_quantity": 180,
                "unit_price": 1.60,
                "reorder_level": 30,
            },
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["stock_quantity"] == 180
        assert float(updated["unit_price"]) == 1.60

        # 5. Low stock filter check
        # Update one drug to have stock below reorder level
        await client.put(
            f"/api/v1/pharmacy/inventory/{drug_id}",
            headers=pharm_headers,
            json={"stock_quantity": 10},
        )
        low_stock_resp = await client.get(
            "/api/v1/pharmacy/inventory?low_stock_only=true",
            headers=pharm_headers,
        )
        assert low_stock_resp.status_code == 200
        low_stock_drugs = low_stock_resp.json()
        assert any(d["id"] == drug_id for d in low_stock_drugs)


@pytest.mark.asyncio
async def test_prescription_dispensing_workflow():
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
        dr_headers = {"Authorization": f"Bearer {dr_login.json()['access_token']}"}

        pharm_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "pharmacist@hospital.com", "password": "Pharmacist@123"},
        )
        pharm_headers = {"Authorization": f"Bearer {pharm_login.json()['access_token']}"}

        # 2. Get Doctor ID
        docs_resp = await client.get("/api/v1/doctors/")
        patel_doc = next(d for d in docs_resp.json() if "Patel" in d["user"]["full_name"])
        doc_id = patel_doc["id"]

        # 3. Register patient and book appointment
        suffix = random_suffix()
        patient_email = f"pharm_patient_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+195{suffix[:7]}",
                "full_name": f"Infection Patient {suffix}",
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
                "slot_time": "11:30",
                "chief_complaint": "Acute bacterial throat infection and fever",
                "symptom_duration": "3 days",
                "severity": "MODERATE",
            },
        )
        apt_id = apt_resp.json()["id"]

        # Compounder approves and checks in
        await client.post(f"/api/v1/appointments/{apt_id}/approve", headers=c_headers)
        checkin_resp = await client.post(
            "/api/v1/queue/check-in",
            headers=c_headers,
            json={"appointment_id": apt_id, "is_priority": False},
        )
        q_id = checkin_resp.json()["id"]
        await client.post("/api/v1/queue/call-patient", headers=c_headers, json={"queue_entry_id": q_id})

        # 4. Check initial stock of "Paracetamol 650mg"
        inv_before = await client.get("/api/v1/pharmacy/inventory?search=Paracetamol", headers=pharm_headers)
        pcm_drug = next(d for d in inv_before.json() if "Paracetamol 650mg" in d["name"])
        initial_pcm_stock = pcm_drug["stock_quantity"]

        # 5. Doctor submits consultation with 2 prescribed medicines
        consult_payload = {
            "appointment_id": apt_id,
            "chief_complaint": "Acute pharyngitis, pyrexia 101.4F",
            "symptoms": "Painful swallowing, fever with chills, body ache",
            "diagnosis": "Acute Streptococcal Pharyngitis",
            "clinical_notes": "Pharyngeal erythema with tonsillar exudates. Clear chest.",
            "special_instructions": "Warm salt water gargles 3x daily. Rest and hydration.",
            "highlights": "Complete entire course of antibiotics even if feeling better.",
            "prescriptions": [
                {
                    "medicine_name": "Paracetamol 650mg",
                    "dosage": "1 tablet",
                    "frequency": "Thrice daily after meals",
                    "duration": "5 days",
                    "instructions": "Take for fever and body ache",
                },
                {
                    "medicine_name": "Amoxicillin 500mg",
                    "dosage": "1 capsule",
                    "frequency": "Twice daily after meals",
                    "duration": "7 days",
                    "instructions": "Complete 7-day antibiotic course",
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
        consult_data = consult_resp.json()
        consult_id = consult_data["id"]
        rx_items = consult_data["prescription_items"]
        assert len(rx_items) == 2

        # 6. Pharmacist views prescription queue
        rx_queue_resp = await client.get("/api/v1/pharmacy/prescriptions", headers=pharm_headers)
        assert rx_queue_resp.status_code == 200
        rx_queue = rx_queue_resp.json()
        matched_rx = next((q for q in rx_queue if q["consultation_id"] == consult_id), None)
        assert matched_rx is not None
        assert matched_rx["patient_name"] == f"Infection Patient {suffix}"
        assert len(matched_rx["items"]) == 2

        # 7. Pharmacist dispenses medicines
        pcm_item = next(it for it in rx_items if "Paracetamol" in it["medicine_name"])
        amox_item = next(it for it in rx_items if "Amoxicillin" in it["medicine_name"])

        dispense_payload = {
            "consultation_id": consult_id,
            "counter_name": "Main Dispensary Window #2",
            "items": [
                {
                    "prescription_item_id": pcm_item["id"],
                    "status": "DISPENSED",
                    "notes": "Dispensed 1 strip of 15 tablets",
                    "quantity_deducted": 15,
                },
                {
                    "prescription_item_id": amox_item["id"],
                    "status": "SUBSTITUTED",
                    "notes": "Substituted with equivalent Augmentin-compatible brand (generic Amoxicillin 500mg)",
                    "quantity_deducted": 14,
                },
            ],
        }

        dispense_resp = await client.post(
            "/api/v1/pharmacy/dispense",
            headers=pharm_headers,
            json=dispense_payload,
        )
        assert dispense_resp.status_code == 200
        dispense_records = dispense_resp.json()
        assert len(dispense_records) == 2
        assert any(r["status"] == "DISPENSED" for r in dispense_records)
        assert any(r["status"] == "SUBSTITUTED" for r in dispense_records)

        # 8. Verify stock deduction
        inv_after = await client.get("/api/v1/pharmacy/inventory?search=Paracetamol", headers=pharm_headers)
        pcm_after = next(d for d in inv_after.json() if "Paracetamol 650mg" in d["name"])
        assert pcm_after["stock_quantity"] == initial_pcm_stock - 15

        # 9. Test unauthorized access: Patient cannot dispense
        unauth_dispense = await client.post(
            "/api/v1/pharmacy/dispense",
            headers=p_headers,
            json=dispense_payload,
        )
        assert unauth_dispense.status_code == 403


@pytest.mark.asyncio
async def test_lab_assistant_sample_collection_and_results():
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

        lab_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "lab@hospital.com", "password": "Lab@123456"},
        )
        lab_headers = {"Authorization": f"Bearer {lab_login.json()['access_token']}"}

        # 2. Get Doctor & Tests
        docs_resp = await client.get("/api/v1/doctors/")
        cardio_doc = next(d for d in docs_resp.json() if "Cardio" in d["specialization"])
        doc_id = cardio_doc["id"]

        catalog_resp = await client.get("/api/v1/lab/catalog")
        catalog = catalog_resp.json()
        cbc_test = next(t for t in catalog if t["code"] == "CBC")

        # 3. Register patient and book appointment
        suffix = random_suffix()
        patient_email = f"lab_patient_{suffix}@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": patient_email,
                "phone": f"+194{suffix[:7]}",
                "full_name": f"Hematology Patient {suffix}",
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
                "slot_time": "09:30",
                "chief_complaint": "Severe fatigue, pallor, and recurrent headaches",
                "symptom_duration": "2 weeks",
                "severity": "MODERATE",
            },
        )
        apt_id = apt_resp.json()["id"]

        # Check in and call turn
        await client.post(f"/api/v1/appointments/{apt_id}/approve", headers=c_headers)
        checkin_resp = await client.post(
            "/api/v1/queue/check-in",
            headers=c_headers,
            json={"appointment_id": apt_id, "is_priority": False},
        )
        q_id = checkin_resp.json()["id"]
        await client.post("/api/v1/queue/call-patient", headers=c_headers, json={"queue_entry_id": q_id})

        # 4. Doctor creates consultation with CBC lab test
        consult_payload = {
            "appointment_id": apt_id,
            "chief_complaint": "Fatigue and microcytic hypochromic pallor evaluation",
            "symptoms": "Shortness of breath on mild exertion, dizziness, brittle nails",
            "diagnosis": "Suspected Iron Deficiency Anemia",
            "clinical_notes": "Conjunctival pallor present. Resting pulse 88 bpm. Heart sounds clear.",
            "special_instructions": "CBC required to determine hemoglobin, hematocrit, and RBC indices.",
            "lab_orders": [
                {
                    "test_id": cbc_test["id"],
                    "instructions": "EDTA whole blood tube required. Measure complete blood count with differential.",
                    "urgency": "URGENT",
                }
            ],
            "finalize": True,
        }
        consult_resp = await client.post("/api/v1/consultations/", headers=dr_headers, json=consult_payload)
        assert consult_resp.status_code == 201
        order_id = consult_resp.json()["lab_orders"][0]["id"]

        # 5. Lab Assistant lists orders and views the test
        order_detail_resp = await client.get(f"/api/v1/lab/orders/{order_id}", headers=lab_headers)
        assert order_detail_resp.status_code == 200
        order_detail = order_detail_resp.json()
        assert order_detail["status"] == "ORDERED"
        assert order_detail["urgency"] == "URGENT"

        # 6. Lab Assistant collects sample
        sample_resp = await client.post(f"/api/v1/lab/orders/{order_id}/collect-sample", headers=lab_headers)
        assert sample_resp.status_code == 200
        sample_data = sample_resp.json()
        assert sample_data["status"] == "SAMPLE_COLLECTED"
        assert sample_data["sample_collected_at"] is not None

        # 7. Lab Assistant submits diagnostic test findings
        result_payload = {
            "result_summary": "Microcytic hypochromic anemia confirmed. Low Hemoglobin (8.4 g/dL) and low MCV (68 fL).",
            "findings_json": {
                "hemoglobin": "8.4 g/dL (Normal: 12.0 - 15.5)",
                "rbc_count": "3.8 x10^6 /uL (Normal: 4.0 - 5.2)",
                "hematocrit": "27.2% (Normal: 36.0 - 46.0)",
                "mcv": "68 fL (Normal: 80 - 100)",
                "mch": "21 pg (Normal: 27 - 33)",
                "platelets": "320 x10^3 /uL (Normal: 150 - 450)",
                "wbc": "6.2 x10^3 /uL (Normal: 4.5 - 11.0)",
            },
            "report_file_url": "https://storage.hospital-system.com/reports/cbc_patient_results.pdf",
            "is_abnormal": True,
            "critical_alert": "Hemoglobin below 9.0 g/dL. Physician review recommended.",
        }

        submit_resp = await client.post(
            f"/api/v1/lab/orders/{order_id}/submit-result",
            headers=lab_headers,
            json=result_payload,
        )
        assert submit_resp.status_code == 201
        result_data = submit_resp.json()
        assert result_data["is_abnormal"] == True
        assert result_data["critical_alert"] is not None
        assert result_data["findings_json"]["hemoglobin"] == "8.4 g/dL (Normal: 12.0 - 15.5)"

        # 8. Verify order is now COMPLETED
        updated_order_resp = await client.get(f"/api/v1/lab/orders/{order_id}", headers=lab_headers)
        assert updated_order_resp.status_code == 200
        updated_order = updated_order_resp.json()
        assert updated_order["status"] == "COMPLETED"
        assert updated_order["result"] is not None
        assert updated_order["result"]["is_abnormal"] == True

        # 9. Verify Patient can view their own lab order and findings
        patient_order_resp = await client.get(f"/api/v1/lab/orders/{order_id}", headers=p_headers)
        assert patient_order_resp.status_code == 200
        p_order = patient_order_resp.json()
        assert p_order["status"] == "COMPLETED"
        assert p_order["result"]["result_summary"].startswith("Microcytic hypochromic")

        # 10. Duplicate submission rejected
        dup_submit = await client.post(
            f"/api/v1/lab/orders/{order_id}/submit-result",
            headers=lab_headers,
            json=result_payload,
        )
        assert dup_submit.status_code == 400
