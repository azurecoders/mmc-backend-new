from datetime import date, datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models.appointment import Appointment
from app.models.doctor import DoctorProfile
from app.models.queue import QueueEntry
from app.models.user import User
from app.schemas.queue import (
    DoctorLiveQueueSummary,
    PatientLiveQueueStatus,
    WaitingRoomTVDisplay,
)

class CRUDQueue:
    async def get_by_id(self, db: AsyncSession, queue_entry_id: uuid.UUID) -> Optional[QueueEntry]:
        stmt = (
            select(QueueEntry)
            .where(QueueEntry.id == queue_entry_id)
            .options(
                joinedload(QueueEntry.appointment),
                joinedload(QueueEntry.doctor).joinedload(DoctorProfile.user),
                joinedload(QueueEntry.doctor).joinedload(DoctorProfile.department),
                joinedload(QueueEntry.patient),
                joinedload(QueueEntry.called_by),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_appointment_id(
        self, db: AsyncSession, appointment_id: uuid.UUID
    ) -> Optional[QueueEntry]:
        stmt = (
            select(QueueEntry)
            .where(QueueEntry.appointment_id == appointment_id)
            .options(
                joinedload(QueueEntry.appointment),
                joinedload(QueueEntry.doctor).joinedload(DoctorProfile.user),
                joinedload(QueueEntry.doctor).joinedload(DoctorProfile.department),
                joinedload(QueueEntry.patient),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_in(
        self,
        db: AsyncSession,
        appointment: Appointment,
        is_priority: bool = False,
    ) -> QueueEntry:
        """
        Checks in an approved or walk-in patient into today's live queue.
        """
        # Check if already in queue
        existing = await self.get_by_appointment_id(db, appointment.id)
        if existing:
            return existing

        now = datetime.now(timezone.utc)
        queue_entry = QueueEntry(
            appointment_id=appointment.id,
            doctor_id=appointment.doctor_id,
            patient_id=appointment.patient_id,
            queue_date=appointment.appointment_date,
            token_number=appointment.token_number,
            status="WAITING",
            is_priority=is_priority,
            check_in_time=now,
        )
        db.add(queue_entry)

        # Update appointment status to CHECKED_IN
        appointment.status = "CHECKED_IN"
        db.add(appointment)

        await db.commit()
        return await self.get_by_id(db, queue_entry.id)

    async def call_patient(
        self,
        db: AsyncSession,
        queue_entry: QueueEntry,
        called_by_user_id: uuid.UUID,
    ) -> QueueEntry:
        """
        Activates patient turn: sets status to CALLED_IN.
        Automatically marks any previously CALLED_IN patient for this doctor as IN_CONSULTATION or COMPLETED.
        """
        now = datetime.now(timezone.utc)

        # Transition any previous CALLED_IN patient for this doctor to IN_CONSULTATION
        stmt_prev = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == queue_entry.doctor_id,
                QueueEntry.queue_date == queue_entry.queue_date,
                QueueEntry.status == "CALLED_IN",
                QueueEntry.id != queue_entry.id,
            )
        )
        result_prev = await db.execute(stmt_prev)
        prev_called = result_prev.scalars().all()
        for p in prev_called:
            p.status = "IN_CONSULTATION"
            if not p.session_start_time:
                p.session_start_time = now
            db.add(p)

        # Activate current patient
        queue_entry.status = "CALLED_IN"
        queue_entry.called_in_time = now
        queue_entry.called_by_user_id = called_by_user_id
        db.add(queue_entry)

        await db.commit()
        return await self.get_by_id(db, queue_entry.id)

    async def start_consultation(
        self, db: AsyncSession, queue_entry: QueueEntry
    ) -> QueueEntry:
        now = datetime.now(timezone.utc)
        queue_entry.status = "IN_CONSULTATION"
        queue_entry.session_start_time = now
        db.add(queue_entry)
        await db.commit()
        return await self.get_by_id(db, queue_entry.id)

    async def complete_consultation(
        self, db: AsyncSession, queue_entry: QueueEntry
    ) -> QueueEntry:
        now = datetime.now(timezone.utc)
        queue_entry.status = "COMPLETED"
        queue_entry.session_end_time = now
        db.add(queue_entry)

        if queue_entry.appointment:
            queue_entry.appointment.status = "COMPLETED"
            db.add(queue_entry.appointment)

        await db.commit()
        return await self.get_by_id(db, queue_entry.id)

    async def hold_patient(
        self, db: AsyncSession, queue_entry: QueueEntry
    ) -> QueueEntry:
        queue_entry.status = "ON_HOLD"
        db.add(queue_entry)
        await db.commit()
        return await self.get_by_id(db, queue_entry.id)

    async def get_patient_live_status(
        self, db: AsyncSession, queue_entry: QueueEntry
    ) -> PatientLiveQueueStatus:
        """
        Calculates dynamic queue position, patients ahead, and estimated wait time.
        """
        doctor = queue_entry.doctor
        avg_mins = doctor.avg_consultation_mins if doctor else 15
        
        # 1. Currently active token being served (CALLED_IN or IN_CONSULTATION)
        stmt_active = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == queue_entry.doctor_id,
                QueueEntry.queue_date == queue_entry.queue_date,
                QueueEntry.status.in_(["CALLED_IN", "IN_CONSULTATION"]),
            )
            .order_by(QueueEntry.called_in_time.desc())
        )
        res_active = await db.execute(stmt_active)
        active_entry = res_active.scalars().first()
        currently_serving = active_entry.token_number if active_entry else None

        # 2. Count waiting patients ahead
        # Priority patients go first, then earlier token numbers
        stmt_ahead = (
            select(func.count(QueueEntry.id))
            .where(
                QueueEntry.doctor_id == queue_entry.doctor_id,
                QueueEntry.queue_date == queue_entry.queue_date,
                QueueEntry.status == "WAITING",
                QueueEntry.id != queue_entry.id,
            )
        )
        if queue_entry.is_priority:
            stmt_ahead = stmt_ahead.where(
                QueueEntry.is_priority == True,
                QueueEntry.token_number < queue_entry.token_number,
            )
        else:
            # If standard patient, all priority patients + standard patients with smaller token number are ahead
            stmt_ahead = stmt_ahead.where(
                (QueueEntry.is_priority == True)
                | (
                    (QueueEntry.is_priority == False)
                    & (QueueEntry.token_number < queue_entry.token_number)
                )
            )

        res_ahead = await db.execute(stmt_ahead)
        patients_ahead = int(res_ahead.scalar_one())

        # If it's already CALLED_IN or IN_CONSULTATION, patients ahead is 0
        if queue_entry.status in ["CALLED_IN", "IN_CONSULTATION"]:
            patients_ahead = 0
            estimated_wait = 0
        elif queue_entry.status in ["COMPLETED", "CANCELLED", "NO_SHOW"]:
            patients_ahead = 0
            estimated_wait = 0
        else:
            estimated_wait = patients_ahead * avg_mins

        doc_name = doctor.user.full_name if (doctor and doctor.user) else "Doctor"
        doc_spec = doctor.specialization if doctor else "Specialist"
        room = doctor.room_number if doctor else "Cabin"

        return PatientLiveQueueStatus(
            appointment_id=queue_entry.appointment_id,
            queue_entry_id=queue_entry.id,
            your_token_number=queue_entry.token_number,
            status=queue_entry.status,
            is_your_turn=(queue_entry.status == "CALLED_IN"),
            currently_serving_token=currently_serving,
            patients_ahead=patients_ahead,
            estimated_wait_time_minutes=estimated_wait,
            is_priority=queue_entry.is_priority,
            doctor_name=doc_name,
            doctor_specialization=doc_spec,
            room_number=room,
            queue_date=queue_entry.queue_date,
        )

    async def get_doctor_live_summary(
        self, db: AsyncSession, doctor_id: uuid.UUID, queue_date: date
    ) -> DoctorLiveQueueSummary:
        # Load doctor details
        stmt_doc = (
            select(DoctorProfile)
            .where(DoctorProfile.id == doctor_id)
            .options(joinedload(DoctorProfile.user))
        )
        res_doc = await db.execute(stmt_doc)
        doctor = res_doc.scalar_one_or_none()

        # Active entry
        stmt_active = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status.in_(["CALLED_IN", "IN_CONSULTATION"]),
            )
            .options(joinedload(QueueEntry.patient))
            .order_by(QueueEntry.called_in_time.desc())
        )
        res_active = await db.execute(stmt_active)
        active_entry = res_active.scalars().first()

        # Waiting entries
        stmt_waiting = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status == "WAITING",
            )
            .order_by(QueueEntry.is_priority.desc(), QueueEntry.token_number.asc())
        )
        res_waiting = await db.execute(stmt_waiting)
        waiting_entries = res_waiting.scalars().all()

        # Completed count
        stmt_comp = (
            select(func.count(QueueEntry.id))
            .where(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status == "COMPLETED",
            )
        )
        res_comp = await db.execute(stmt_comp)
        completed_count = int(res_comp.scalar_one())

        doc_name = doctor.user.full_name if (doctor and doctor.user) else "Doctor"
        spec = doctor.specialization if doctor else "Specialist"
        room = doctor.room_number if doctor else "Cabin"

        return DoctorLiveQueueSummary(
            doctor_id=doctor_id,
            doctor_name=doc_name,
            specialization=spec,
            room_number=room,
            active_token=active_entry.token_number if active_entry else None,
            active_token_status=active_entry.status if active_entry else None,
            active_patient_name=active_entry.patient.full_name if (active_entry and active_entry.patient) else None,
            total_waiting=len(waiting_entries),
            total_completed_today=completed_count,
            upcoming_tokens=[w.token_number for w in waiting_entries[:8]],
        )

    async def get_tv_display_summary(
        self, db: AsyncSession, queue_date: date
    ) -> WaitingRoomTVDisplay:
        # Include all registered doctors so patient lounge can see all cabin numbers
        stmt_docs = select(DoctorProfile.id)
        res_docs = await db.execute(stmt_docs)
        doc_ids = res_docs.scalars().all()

        summaries: List[DoctorLiveQueueSummary] = []
        for d_id in doc_ids:
            summary = await self.get_doctor_live_summary(db, d_id, queue_date)
            summaries.append(summary)

        # Prioritize active cabins, then cabins with waiting patients
        summaries.sort(
            key=lambda s: (s.active_token is not None, s.total_waiting > 0, s.total_completed_today),
            reverse=True,
        )

        return WaitingRoomTVDisplay(
            hospital_name="ApexCare Hospital & Medical Center",
            queue_date=queue_date,
            doctors=summaries,
        )

    async def get_doctor_queue_entries(
        self, db: AsyncSession, doctor_id: uuid.UUID, queue_date: date
    ) -> List[QueueEntry]:
        stmt = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
            )
            .options(
                joinedload(QueueEntry.patient),
                joinedload(QueueEntry.appointment),
            )
            .order_by(QueueEntry.is_priority.desc(), QueueEntry.token_number.asc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

crud_queue = CRUDQueue()
