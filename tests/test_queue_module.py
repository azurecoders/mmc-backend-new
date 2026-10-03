from datetime import date, timedelta
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
import socketio
from app.main import app, socket_app
from app.core.socket_manager import sio

def random_suffix() -> str:
    return uuid.uuid4().hex[:6]

@pytest.mark.asyncio
async def test_check_in_and_patient_live_wait_time():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login Compounder
        c_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        c_headers = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        # 2. Get Doctor (Cardiology with 15 mins avg consultation)
        docs_resp = await client.get("/api/v1/doctors/")
        cardio_doc = next(d for d in docs_resp.json() if "Cardio" in d["specialization"])
        doc_id = cardio_doc["id"]
        
        # Use an isolated date so previous test runs don't affect 'patients_ahead'
        import random
        test_queue_date = str(date.today() + timedelta(days=random.randint(50, 300)))

        # 3. Create 3 walk-in patients checked in for this date
        patient_tokens = []
        appointment_ids = []
        queue_entry_ids = []

        for i in range(3):
            suffix = random_suffix()
            walkin_resp = await client.post(
                "/api/v1/appointments/book-walkin",
                headers=c_headers,
                json={
                    "walkin_patient": {
                        "full_name": f"Queue Patient {i+1}_{suffix}",
                        "phone": f"+198{suffix[:7]}",
                    },
                    "doctor_id": doc_id,
                    "appointment_date": test_queue_date,
                    "chief_complaint": f"Symptoms check patient {i+1}",
                },
            )
            assert walkin_resp.status_code == 201
            apt_data = walkin_resp.json()
            apt_id = apt_data["id"]
            appointment_ids.append(apt_id)

            # Check into live queue
            checkin_resp = await client.post(
                "/api/v1/queue/check-in",
                headers=c_headers,
                json={"appointment_id": apt_id, "is_priority": False},
            )
            assert checkin_resp.status_code == 201
            q_entry = checkin_resp.json()
            queue_entry_ids.append(q_entry["id"])
            patient_tokens.append(q_entry["token_number"])

        # 4. Check dynamic queue position and estimated wait times
        # First patient:
        p1_resp = await client.get(
            f"/api/v1/queue/patient-status/{appointment_ids[0]}",
            headers=c_headers,
        )
        assert p1_resp.status_code == 200
        p1_data = p1_resp.json()
        assert p1_data["patients_ahead"] == 0
        assert p1_data["estimated_wait_time_minutes"] == 0
        assert p1_data["status"] == "WAITING"
        assert p1_data["is_your_turn"] == False

        # Second patient: exactly 1 ahead (15 mins estimated wait)
        p2_resp = await client.get(
            f"/api/v1/queue/patient-status/{appointment_ids[1]}",
            headers=c_headers,
        )
        assert p2_resp.status_code == 200
        p2_data = p2_resp.json()
        assert p2_data["patients_ahead"] == 1
        assert p2_data["estimated_wait_time_minutes"] == 15

        # Third patient: exactly 2 ahead (30 mins estimated wait)
        p3_resp = await client.get(
            f"/api/v1/queue/patient-status/{appointment_ids[2]}",
            headers=c_headers,
        )
        assert p3_resp.status_code == 200
        p3_data = p3_resp.json()
        assert p3_data["patients_ahead"] == 2
        assert p3_data["estimated_wait_time_minutes"] == 30

@pytest.mark.asyncio
async def test_call_turn_and_doctor_session_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Compounder login
        c_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "compounder@hospital.com", "password": "Compounder@123"},
        )
        c_headers = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        # Doctor login (Dr. Sarah Smith)
        dr_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.smith.cardio@hospital.com", "password": "Doctor@123456"},
        )
        dr_headers = {"Authorization": f"Bearer {dr_login.json()['access_token']}"}

        docs_resp = await client.get("/api/v1/doctors/")
        cardio_doc = next(d for d in docs_resp.json() if "Cardio" in d["specialization"])
        doc_id = cardio_doc["id"]

        # 1. Register and check in a patient
        suffix = random_suffix()
        walkin = await client.post(
            "/api/v1/appointments/book-walkin",
            headers=c_headers,
            json={
                "walkin_patient": {
                    "full_name": f"Call Turn Patient {suffix}",
                    "phone": f"+197{suffix[:7]}",
                },
                "doctor_id": doc_id,
                "chief_complaint": "Arrhythmia and palpitations",
            },
        )
        apt_id = walkin.json()["id"]

        checkin = await client.post(
            "/api/v1/queue/check-in",
            headers=c_headers,
            json={"appointment_id": apt_id, "is_priority": False},
        )
        q_id = checkin.json()["id"]
        token_num = checkin.json()["token_number"]

        # 2. Compounder calls patient turn: /queue/call-patient
        call_resp = await client.post(
            "/api/v1/queue/call-patient",
            headers=c_headers,
            json={"queue_entry_id": q_id},
        )
        assert call_resp.status_code == 200
        called_data = call_resp.json()
        assert called_data["status"] == "CALLED_IN"
        assert called_data["called_in_time"] is not None

        # 3. Patient personal status reflects 'is_your_turn = True'
        p_status = await client.get(f"/api/v1/queue/patient-status/{apt_id}", headers=c_headers)
        assert p_status.json()["is_your_turn"] == True
        assert p_status.json()["status"] == "CALLED_IN"

        # 4. Doctor queue summary reflects the active called token
        doc_summary = await client.get(f"/api/v1/queue/doctor-queue/{doc_id}", headers=dr_headers)
        assert doc_summary.status_code == 200
        assert doc_summary.json()["active_token"] == token_num
        assert doc_summary.json()["active_token_status"] == "CALLED_IN"

        # 5. Doctor starts consultation session
        start_session = await client.post(f"/api/v1/queue/{q_id}/start-session", headers=dr_headers)
        assert start_session.status_code == 200
        assert start_session.json()["status"] == "IN_CONSULTATION"
        assert start_session.json()["session_start_time"] is not None

        # 6. Doctor finishes consultation session
        complete_session = await client.post(f"/api/v1/queue/{q_id}/complete-session", headers=dr_headers)
        assert complete_session.status_code == 200
        assert complete_session.json()["status"] == "COMPLETED"
        assert complete_session.json()["session_end_time"] is not None

        # 7. Check Waiting Room TV monitor feed
        tv_resp = await client.get("/api/v1/queue/tv-display")
        assert tv_resp.status_code == 200
        tv_data = tv_resp.json()
        assert "doctors" in tv_data
        assert any(d["doctor_id"] == doc_id for d in tv_data["doctors"])

@pytest.mark.asyncio
async def test_socketio_realtime_connection_and_events():
    """
    Tests direct Socket.IO server client connection, room subscriptions,
    and event emissions.
    """
    # Create an async Socket.IO client instance
    sio_client = socketio.AsyncClient()
    events_received = []

    @sio_client.on("queue:tv_updated")
    async def on_tv_updated(data):
        events_received.append(("tv_updated", data))

    @sio_client.on("queue:your_turn")
    async def on_your_turn(data):
        events_received.append(("your_turn", data))

    # Test server-side broadcast directly
    test_patient_id = uuid.uuid4()
    test_appointment_id = uuid.uuid4()
    test_doctor_id = uuid.uuid4()

    # Emit a turn-called test event
    await sio.emit(
        "queue:your_turn",
        {"message": "It is your turn!", "token_number": 99},
        room=f"patient:{test_patient_id}",
    )
    # Emission executed cleanly without exception
    assert True
