from datetime import datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from app.models.appointment import Appointment
from app.models.consultation import Consultation, PrescriptionItem
from app.models.doctor import DoctorProfile
from app.models.lab import LabOrder
from app.models.queue import QueueEntry
from app.schemas.consultation import ConsultationCreate, ConsultationUpdate

class CRUDConsultation:
    async def get_by_id(self, db: AsyncSession, consultation_id: uuid.UUID) -> Optional[Consultation]:
        stmt = (
            select(Consultation)
            .where(Consultation.id == consultation_id)
            .options(
                joinedload(Consultation.appointment),
                joinedload(Consultation.doctor).joinedload(DoctorProfile.user),
                joinedload(Consultation.doctor).joinedload(DoctorProfile.department),
                joinedload(Consultation.patient),
                selectinload(Consultation.prescription_items),
                selectinload(Consultation.lab_orders).joinedload(LabOrder.test),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_appointment_id(
        self, db: AsyncSession, appointment_id: uuid.UUID
    ) -> Optional[Consultation]:
        stmt = (
            select(Consultation)
            .where(Consultation.appointment_id == appointment_id)
            .options(
                joinedload(Consultation.appointment),
                joinedload(Consultation.doctor).joinedload(DoctorProfile.user),
                joinedload(Consultation.doctor).joinedload(DoctorProfile.department),
                joinedload(Consultation.patient),
                selectinload(Consultation.prescription_items),
                selectinload(Consultation.lab_orders).joinedload(LabOrder.test),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        patient_id: Optional[uuid.UUID] = None,
        doctor_id: Optional[uuid.UUID] = None,
    ) -> List[Consultation]:
        stmt = (
            select(Consultation)
            .options(
                joinedload(Consultation.appointment),
                joinedload(Consultation.doctor).joinedload(DoctorProfile.user),
                joinedload(Consultation.patient),
                selectinload(Consultation.prescription_items),
                selectinload(Consultation.lab_orders).joinedload(LabOrder.test),
            )
            .order_by(Consultation.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if patient_id:
            stmt = stmt.where(Consultation.patient_id == patient_id)
        if doctor_id:
            stmt = stmt.where(Consultation.doctor_id == doctor_id)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        appointment: Appointment,
        obj_in: ConsultationCreate,
    ) -> Consultation:
        now = datetime.now(timezone.utc)
        
        consultation = Consultation(
            appointment_id=appointment.id,
            doctor_id=appointment.doctor_id,
            patient_id=appointment.patient_id,
            chief_complaint=obj_in.chief_complaint.strip(),
            symptoms=obj_in.symptoms.strip() if obj_in.symptoms else None,
            diagnosis=obj_in.diagnosis.strip(),
            clinical_notes=obj_in.clinical_notes.strip(),
            special_instructions=obj_in.special_instructions.strip() if obj_in.special_instructions else None,
            highlights=obj_in.highlights.strip() if obj_in.highlights else None,
            follow_up_date=obj_in.follow_up_date,
            is_finalized=obj_in.finalize,
            finalized_at=now if obj_in.finalize else None,
        )
        db.add(consultation)
        await db.flush()

        # Add Prescription Items
        items_to_add = obj_in.prescriptions or obj_in.prescription_items or []
        for item in items_to_add:
            rx_item = PrescriptionItem(
                consultation_id=consultation.id,
                medicine_name=item.medicine_name.strip(),
                dosage=item.dosage.strip(),
                frequency=item.frequency.strip(),
                duration=item.duration.strip(),
                instructions=item.instructions.strip() if item.instructions else None,
                dispense_status="PENDING",
            )
            db.add(rx_item)

        # Add Lab Orders
        for order in obj_in.lab_orders:
            lab_order = LabOrder(
                consultation_id=consultation.id,
                test_id=order.test_id,
                patient_id=appointment.patient_id,
                doctor_id=appointment.doctor_id,
                instructions=order.instructions.strip() if order.instructions else None,
                urgency=order.urgency.upper(),
                status="ORDERED",
            )
            db.add(lab_order)

        # If finalized, mark appointment and queue entry as COMPLETED
        if obj_in.finalize:
            appointment.status = "COMPLETED"
            db.add(appointment)

            stmt_q = select(QueueEntry).where(QueueEntry.appointment_id == appointment.id)
            res_q = await db.execute(stmt_q)
            q_entry = res_q.scalar_one_or_none()
            if q_entry:
                q_entry.status = "COMPLETED"
                q_entry.session_end_time = now
                db.add(q_entry)

        await db.commit()
        return await self.get_by_id(db, consultation.id)

    async def update(
        self,
        db: AsyncSession,
        db_obj: Consultation,
        obj_in: ConsultationUpdate,
    ) -> Consultation:
        if obj_in.chief_complaint is not None:
            db_obj.chief_complaint = obj_in.chief_complaint.strip()
        if obj_in.symptoms is not None:
            db_obj.symptoms = obj_in.symptoms.strip()
        if obj_in.diagnosis is not None:
            db_obj.diagnosis = obj_in.diagnosis.strip()
        if obj_in.clinical_notes is not None:
            db_obj.clinical_notes = obj_in.clinical_notes.strip()
        if obj_in.special_instructions is not None:
            db_obj.special_instructions = obj_in.special_instructions.strip()
        if obj_in.highlights is not None:
            db_obj.highlights = obj_in.highlights.strip()
        if obj_in.follow_up_date is not None:
            db_obj.follow_up_date = obj_in.follow_up_date
            
        if obj_in.is_finalized is not None and obj_in.is_finalized and not db_obj.is_finalized:
            now = datetime.now(timezone.utc)
            db_obj.is_finalized = True
            db_obj.finalized_at = now
            if db_obj.appointment:
                db_obj.appointment.status = "COMPLETED"
                db.add(db_obj.appointment)

        db.add(db_obj)
        await db.commit()
        return await self.get_by_id(db, db_obj.id)

crud_consultation = CRUDConsultation()
