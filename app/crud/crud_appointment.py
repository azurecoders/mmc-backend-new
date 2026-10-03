from datetime import date, datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from app.models.appointment import Appointment
from app.models.doctor import DoctorProfile
from app.schemas.appointment import AppointmentOnlineBooking, AppointmentWalkinBooking

def generate_appointment_code(app_date: date) -> str:
    date_str = app_date.strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:6].upper()
    return f"APT-{date_str}-{random_part}"

class CRUDAppointment:
    async def get_by_id(self, db: AsyncSession, appointment_id: uuid.UUID) -> Optional[Appointment]:
        stmt = (
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.user),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.department),
                joinedload(Appointment.doctor).selectinload(DoctorProfile.schedules),
                joinedload(Appointment.verified_by_compounder),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(self, db: AsyncSession, appointment_number: str) -> Optional[Appointment]:
        stmt = (
            select(Appointment)
            .where(Appointment.appointment_number == appointment_number.strip().upper())
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.user),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.department),
                joinedload(Appointment.verified_by_compounder),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_token_number(
        self, db: AsyncSession, doctor_id: uuid.UUID, appointment_date: date
    ) -> int:
        stmt = select(func.coalesce(func.max(Appointment.token_number), 0) + 1).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
        )
        result = await db.execute(stmt)
        return int(result.scalar_one())

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        patient_id: Optional[uuid.UUID] = None,
        doctor_id: Optional[uuid.UUID] = None,
        appointment_date: Optional[date] = None,
        status: Optional[str] = None,
        booking_type: Optional[str] = None,
    ) -> List[Appointment]:
        stmt = (
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.user),
                joinedload(Appointment.doctor).joinedload(DoctorProfile.department),
                joinedload(Appointment.verified_by_compounder),
            )
            .order_by(Appointment.appointment_date.asc(), Appointment.token_number.asc())
            .offset(skip)
            .limit(limit)
        )
        if patient_id:
            stmt = stmt.where(Appointment.patient_id == patient_id)
        if doctor_id:
            stmt = stmt.where(Appointment.doctor_id == doctor_id)
        if appointment_date:
            stmt = stmt.where(Appointment.appointment_date == appointment_date)
        if status:
            stmt = stmt.where(Appointment.status == status.upper())
        if booking_type:
            stmt = stmt.where(Appointment.booking_type == booking_type.upper())

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_online(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        obj_in: AppointmentOnlineBooking,
        token_number: int,
    ) -> Appointment:
        appointment = Appointment(
            appointment_number=generate_appointment_code(obj_in.appointment_date),
            patient_id=patient_id,
            doctor_id=obj_in.doctor_id,
            booking_type="ONLINE",
            appointment_date=obj_in.appointment_date,
            slot_time=obj_in.slot_time,
            token_number=token_number,
            chief_complaint=obj_in.chief_complaint.strip(),
            symptom_duration=obj_in.symptom_duration,
            severity=obj_in.severity.upper() if obj_in.severity else "MODERATE",
            ai_recommended_department=obj_in.ai_recommended_department,
            ai_recommendation_reason=obj_in.ai_recommendation_reason,
            status="PENDING_APPROVAL",
        )
        db.add(appointment)
        await db.commit()
        return await self.get_by_id(db, appointment.id)

    async def create_walkin(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        doctor_id: uuid.UUID,
        chief_complaint: str,
        compounder_id: uuid.UUID,
        appointment_date: Optional[date] = None,
        slot_time: Optional[str] = None,
        symptom_duration: Optional[str] = None,
        severity: Optional[str] = "MODERATE",
    ) -> Appointment:
        today = appointment_date or date.today()
        current_time = slot_time or datetime.now().strftime("%H:%M")
        token_num = await self.get_next_token_number(db, doctor_id, today)

        now = datetime.now(timezone.utc)
        appointment = Appointment(
            appointment_number=generate_appointment_code(today),
            patient_id=patient_id,
            doctor_id=doctor_id,
            booking_type="WALK_IN",
            appointment_date=today,
            slot_time=current_time,
            token_number=token_num,
            chief_complaint=chief_complaint.strip(),
            symptom_duration=symptom_duration,
            severity=severity.upper() if severity else "MODERATE",
            status="APPROVED",  # Walk-in patients registered by compounder are approved immediately
            verified_by_compounder_id=compounder_id,
            verified_at=now,
        )
        db.add(appointment)
        await db.commit()
        return await self.get_by_id(db, appointment.id)

    async def approve(
        self,
        db: AsyncSession,
        appointment: Appointment,
        compounder_id: uuid.UUID,
    ) -> Appointment:
        appointment.status = "APPROVED"
        appointment.verified_by_compounder_id = compounder_id
        appointment.verified_at = datetime.now(timezone.utc)
        appointment.rejection_reason = None
        db.add(appointment)
        await db.commit()
        return await self.get_by_id(db, appointment.id)

    async def reject(
        self,
        db: AsyncSession,
        appointment: Appointment,
        compounder_id: uuid.UUID,
        reason: str,
    ) -> Appointment:
        appointment.status = "REJECTED"
        appointment.verified_by_compounder_id = compounder_id
        appointment.verified_at = datetime.now(timezone.utc)
        appointment.rejection_reason = reason.strip()
        db.add(appointment)
        await db.commit()
        return await self.get_by_id(db, appointment.id)

crud_appointment = CRUDAppointment()
