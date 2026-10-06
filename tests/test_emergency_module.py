import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_emergency_code_and_teams_workflow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login as Super Admin
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "admin@hospital.com", "password": "Admin@123456"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # 2. Login as Nurse
        nurse_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "nurse@hospital.com", "password": "Nurse@123"},
        )
        assert nurse_login.status_code == 200
        nurse_data = nurse_login.json()
        nurse_headers = {"Authorization": f"Bearer {nurse_data['access_token']}"}
        nurse_id = nurse_data["user"]["id"]

        # 3. Login as Doctor
        doc_login = await client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "dr.smith.cardio@hospital.com", "password": "Doctor@123456"},
        )
        assert doc_login.status_code == 200
        doc_data = doc_login.json()
        doc_headers = {"Authorization": f"Bearer {doc_data['access_token']}"}
        doc_id = doc_data["user"]["id"]

        # 4. Check Hospital Wards
        wards_resp = await client.get("/api/v1/emergency/wards", headers=nurse_headers)
        assert wards_resp.status_code == 200
        wards = wards_resp.json()
        assert len(wards) >= 5
        assert "ICU — Intensive Care Unit" in wards

        # 5. List Emergency Code Groups
        groups_resp = await client.get("/api/v1/emergency/groups", headers=admin_headers)
        assert groups_resp.status_code == 200
        groups = groups_resp.json()
        group_codes = [g["code"] for g in groups]
        assert "CODE_BLUE" in group_codes
        assert "CODE_RED" in group_codes
        assert "RAPID_RESPONSE" in group_codes

        # 6. Admin adds Doctor to CODE_BLUE group
        add_doc_resp = await client.post(
            "/api/v1/emergency/groups/CODE_BLUE/members",
            headers=admin_headers,
            json={"user_id": doc_id},
        )
        assert add_doc_resp.status_code == 200
        updated_blue = add_doc_resp.json()
        blue_member_ids = [m["id"] for m in updated_blue["members"]]
        assert doc_id in blue_member_ids

        # 7. Nurse triggers CODE_BLUE alert in ICU
        trigger_resp = await client.post(
            "/api/v1/emergency/trigger",
            headers=nurse_headers,
            json={
                "code": "CODE_BLUE",
                "ward": "ICU — Intensive Care Unit",
                "location_details": "Bed 4, Room 102",
                "notes": "Patient unarousable, pulseless, CPR initiated by primary nurse.",
            },
        )
        assert trigger_resp.status_code == 201
        alert = trigger_resp.json()
        alert_id = alert["id"]
        assert alert["code"] == "CODE_BLUE"
        assert alert["ward"] == "ICU — Intensive Care Unit"
        assert alert["status"] == "ACTIVE"
        assert alert["assigned_members_count"] >= 1

        # 8. Check Active Alerts
        active_resp = await client.get("/api/v1/emergency/active", headers=doc_headers)
        assert active_resp.status_code == 200
        active_list = active_resp.json()
        assert any(a["id"] == alert_id for a in active_list)

        # 9. Doctor acknowledges code (en route)
        ack_resp = await client.post(
            f"/api/v1/emergency/alerts/{alert_id}/acknowledge",
            headers=doc_headers,
            json={"note": "Cardiology crash team running to ICU Bed 4 with defibrillator"},
        )
        assert ack_resp.status_code == 200
        ack_data = ack_resp.json()
        assert ack_data["status"] == "ACKNOWLEDGED"
        assert ack_data["responders_count"] >= 1
        assert any(r["user_id"] == doc_id for r in ack_data["responders"])

        # 10. Nurse resolves alert after resuscitation
        resolve_resp = await client.post(
            f"/api/v1/emergency/alerts/{alert_id}/resolve",
            headers=nurse_headers,
            json={"resolution_notes": "ROSC achieved after 2 cycles of CPR and 1 shock. Vitals stabilized."},
        )
        assert resolve_resp.status_code == 200
        resolved_data = resolve_resp.json()
        assert resolved_data["status"] == "RESOLVED"
        assert resolved_data["resolved_at"] is not None

        # Verify no longer active
        active_after = await client.get("/api/v1/emergency/active", headers=doc_headers)
        assert active_after.status_code == 200
        assert not any(a["id"] == alert_id for a in active_after.json())

        # 11. Admin removes Doctor from CODE_BLUE group
        del_resp = await client.delete(
            f"/api/v1/emergency/groups/CODE_BLUE/members/{doc_id}",
            headers=admin_headers,
        )
        assert del_resp.status_code == 200
        del_group = del_resp.json()
        del_member_ids = [m["id"] for m in del_group["members"]]
        assert doc_id not in del_member_ids
