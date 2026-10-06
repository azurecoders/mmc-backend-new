import logging
import uuid
from typing import Any, Dict, Optional
import socketio
from app.core.security import decode_token

logger = logging.getLogger(__name__)

# Initialize Socket.IO AsyncServer with CORS enabled
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

@sio.event
async def connect(sid: str, environ: Dict[str, Any], auth: Optional[Dict[str, Any]] = None):
    """
    Handles client WebSocket connection.
    Authenticates token if provided and joins role/user rooms.
    """
    token = None
    if auth and isinstance(auth, dict):
        token = auth.get("token")
    
    if not token and "QUERY_STRING" in environ:
        # Extract token from query parameters: ?token=...
        query = environ["QUERY_STRING"]
        for param in query.split("&"):
            if param.startswith("token="):
                token = param.split("=")[1]
                break

    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
            roles = payload.get("roles", [])
            
            # Save session data
            await sio.save_session(sid, {"user_id": user_id, "roles": roles})
            
            # Join user personal room
            await sio.enter_room(sid, f"user:{user_id}")
            
            if "PATIENT" in roles:
                await sio.enter_room(sid, f"patient:{user_id}")
            if "COMPOUNDER" in roles or "SUPER_ADMIN" in roles:
                await sio.enter_room(sid, "compounder:queue")
            if "PHARMACIST" in roles or "SUPER_ADMIN" in roles:
                await sio.enter_room(sid, "pharmacy:orders")
            if "LAB_ASSISTANT" in roles or "SUPER_ADMIN" in roles:
                await sio.enter_room(sid, "lab:orders")
            if any(r in roles for r in ["DOCTOR", "NURSE", "COMPOUNDER", "SUPER_ADMIN"]):
                await sio.enter_room(sid, "staff:emergency")
                
            logger.info(f"Socket connected: sid={sid} user={user_id} roles={roles}")
            return True
        except Exception as e:
            logger.warning(f"Socket token validation failed for sid={sid}: {e}")
            # Allow connection as guest/public viewer (e.g., waiting room TV display)

    logger.info(f"Socket connected anonymously (public screen/guest): sid={sid}")
    return True

@sio.event
async def disconnect(sid: str):
    logger.info(f"Socket disconnected: sid={sid}")

@sio.event
async def join_room(sid: str, data: Dict[str, Any]):
    """
    Allows clients to join public or specific monitor rooms, e.g.:
    - "queue:tv" (TV monitor)
    - "doctor:{doctor_id}"
    - "appointment:{appointment_id}"
    """
    room = data.get("room")
    if room:
        await sio.enter_room(sid, room)
        logger.info(f"Client {sid} joined room: {room}")
        return {"status": "joined", "room": room}
    return {"status": "error", "message": "No room specified"}

@sio.event
async def leave_room(sid: str, data: Dict[str, Any]):
    room = data.get("room")
    if room:
        await sio.leave_room(sid, room)
        logger.info(f"Client {sid} left room: {room}")
        return {"status": "left", "room": room}
    return {"status": "error", "message": "No room specified"}

class SocketBroadcastManager:
    """
    High-performance real-time broadcast helper.
    """
    @staticmethod
    async def emit_queue_change(
        doctor_id: uuid.UUID,
        doctor_summary: Dict[str, Any],
        waiting_room_summary: Optional[Dict[str, Any]] = None,
    ):
        """
        Broadcasts live queue changes to Doctor Cabin, TV Screens, and Compounders.
        """
        # 1. Update the specific doctor cabin
        await sio.emit("queue:doctor_updated", doctor_summary, room=f"doctor:{doctor_id}")
        
        # 2. Update the TV Waiting Room screens
        if waiting_room_summary:
            await sio.emit("queue:tv_updated", waiting_room_summary, room="queue:tv")
            
        # 3. Update all Compounders managing queues
        await sio.emit("queue:compounder_updated", doctor_summary, room="compounder:queue")

    @staticmethod
    async def emit_turn_called(
        patient_id: uuid.UUID,
        appointment_id: uuid.UUID,
        doctor_id: uuid.UUID,
        call_payload: Dict[str, Any],
    ):
        """
        High-priority turn calling alert.
        Instantly notifies both Patient and Doctor.
        """
        # Notify the patient on personal room & appointment room
        await sio.emit("queue:your_turn", call_payload, room=f"patient:{patient_id}")
        await sio.emit("queue:your_turn", call_payload, room=f"appointment:{appointment_id}")
        
        # Notify the Doctor cabin
        await sio.emit("queue:next_patient_ready", call_payload, room=f"doctor:{doctor_id}")

        # Broadcast turn call to TV monitor (triggers sound/visual flash)
        await sio.emit("queue:token_called_tv", call_payload, room="queue:tv")

    @staticmethod
    async def emit_patient_status_update(
        patient_id: uuid.UUID,
        appointment_id: uuid.UUID,
        status_payload: Dict[str, Any],
    ):
        """
        Sends personalized queue progress (tokens ahead, estimated wait time).
        """
        await sio.emit("queue:patient_status", status_payload, room=f"patient:{patient_id}")
        await sio.emit("queue:patient_status", status_payload, room=f"appointment:{appointment_id}")

    @staticmethod
    async def emit_consultation_completed(
        patient_id: uuid.UUID,
        appointment_id: uuid.UUID,
        consultation_summary: Dict[str, Any],
    ):
        """
        Notifies patient device immediately with consultation notes & prescription.
        """
        await sio.emit("consultation:finalized", consultation_summary, room=f"patient:{patient_id}")
        await sio.emit("consultation:finalized", consultation_summary, room=f"appointment:{appointment_id}")

    @staticmethod
    async def emit_prescription_to_pharmacy(prescription_payload: Dict[str, Any]):
        """
        Notifies the pharmacy department in real time when doctor prescribes medication.
        """
        await sio.emit("pharmacy:new_prescription", prescription_payload, room="pharmacy:orders")

    @staticmethod
    async def emit_lab_orders_to_lab(lab_payload: Dict[str, Any]):
        """
        Notifies lab assistants in real time when doctor orders diagnostic tests.
        """
        await sio.emit("lab:new_orders", lab_payload, room="lab:orders")

    @staticmethod
    async def emit_prescription_dispensed(
        patient_id: uuid.UUID,
        appointment_id: uuid.UUID,
        alert_payload: Dict[str, Any],
    ):
        """
        Notifies patient that prescribed medications are dispensed and ready for pickup.
        """
        await sio.emit("pharmacy:prescription_dispensed", alert_payload, room=f"patient:{patient_id}")
        await sio.emit("pharmacy:prescription_dispensed", alert_payload, room=f"appointment:{appointment_id}")

    @staticmethod
    async def emit_lab_result_ready(
        patient_id: uuid.UUID,
        doctor_id: uuid.UUID,
        result_payload: Dict[str, Any],
    ):
        """
        Notifies patient and doctor that lab diagnostic report is complete.
        """
        await sio.emit("lab:report_completed", result_payload, room=f"patient:{patient_id}")
        await sio.emit("lab:report_completed", result_payload, room=f"doctor:{doctor_id}")

    @staticmethod
    async def emit_critical_vitals_alert(
        doctor_id: uuid.UUID,
        patient_id: uuid.UUID,
        alert_payload: Dict[str, Any],
    ):
        """
        Urgent critical alert directly to the attending/primary doctor's cabin and phone.
        """
        await sio.emit("patient:critical_vitals_alert", alert_payload, room=f"doctor:{doctor_id}")
        await sio.emit("patient:critical_vitals_alert", alert_payload, room=f"patient:{patient_id}")

    @staticmethod
    async def emit_queue_priority_escalation(
        doctor_id: uuid.UUID,
        escalation_payload: Dict[str, Any],
    ):
        """
        Broadcasts emergency priority escalation in the live queue for compounder and doctor.
        """
        await sio.emit("queue:emergency_priority", escalation_payload, room=f"doctor:{doctor_id}")
        await sio.emit("queue:emergency_priority", escalation_payload, room="compounder:queue")
        await sio.emit("queue:tv_updated", escalation_payload, room="queue:tv")

socket_manager = SocketBroadcastManager()
