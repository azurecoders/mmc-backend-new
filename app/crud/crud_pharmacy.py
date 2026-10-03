import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from app.models.consultation import Consultation, PrescriptionItem
from app.models.pharmacy import MedicineDispenseRecord, PharmacyMedicine
from app.schemas.pharmacy import (
    DispenseItemRequest,
    PharmacyMedicineCreate,
    PharmacyMedicineUpdate,
    PharmacyPrescriptionQueueItem,
    PrescriptionItemResponse,
)

class CRUDPharmacy:
    async def get_medicine_by_id(self, db: AsyncSession, medicine_id: uuid.UUID) -> Optional[PharmacyMedicine]:
        stmt = select(PharmacyMedicine).where(PharmacyMedicine.id == medicine_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_medicine_by_name(self, db: AsyncSession, name: str) -> Optional[PharmacyMedicine]:
        stmt = select(PharmacyMedicine).where(PharmacyMedicine.name.ilike(name.strip()))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_inventory(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        category: Optional[str] = None,
        search: Optional[str] = None,
        low_stock_only: bool = False,
    ) -> List[PharmacyMedicine]:
        stmt = select(PharmacyMedicine).offset(skip).limit(limit).order_by(PharmacyMedicine.name)
        if category:
            stmt = stmt.where(PharmacyMedicine.category == category.upper())
        if search:
            stmt = stmt.where(
                PharmacyMedicine.name.ilike(f"%{search.strip()}%")
                | PharmacyMedicine.generic_name.ilike(f"%{search.strip()}%")
            )
        if low_stock_only:
            stmt = stmt.where(PharmacyMedicine.stock_quantity <= PharmacyMedicine.reorder_level)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_medicine(self, db: AsyncSession, obj_in: PharmacyMedicineCreate) -> PharmacyMedicine:
        med = PharmacyMedicine(
            name=obj_in.name.strip(),
            generic_name=obj_in.generic_name.strip(),
            category=obj_in.category.upper().strip(),
            dosage_form=obj_in.dosage_form.upper().strip(),
            unit_price=obj_in.unit_price,
            stock_quantity=obj_in.stock_quantity,
            reorder_level=obj_in.reorder_level,
            is_active=obj_in.is_active,
        )
        db.add(med)
        await db.commit()
        await db.refresh(med)
        return med

    async def update_medicine(
        self, db: AsyncSession, db_obj: PharmacyMedicine, obj_in: PharmacyMedicineUpdate
    ) -> PharmacyMedicine:
        if obj_in.name is not None:
            db_obj.name = obj_in.name.strip()
        if obj_in.generic_name is not None:
            db_obj.generic_name = obj_in.generic_name.strip()
        if obj_in.category is not None:
            db_obj.category = obj_in.category.upper().strip()
        if obj_in.dosage_form is not None:
            db_obj.dosage_form = obj_in.dosage_form.upper().strip()
        if obj_in.unit_price is not None:
            db_obj.unit_price = obj_in.unit_price
        if obj_in.stock_quantity is not None:
            db_obj.stock_quantity = obj_in.stock_quantity
        if obj_in.reorder_level is not None:
            db_obj.reorder_level = obj_in.reorder_level
        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def get_prescription_queue(
        self, db: AsyncSession, skip: int = 0, limit: int = 50
    ) -> List[PharmacyPrescriptionQueueItem]:
        """
        Retrieves all consultations that have prescription items.
        """
        stmt = (
            select(Consultation)
            .where(Consultation.is_finalized == True)
            .join(Consultation.prescription_items)
            .options(
                joinedload(Consultation.patient),
                joinedload(Consultation.doctor).joinedload(Consultation.doctor.property.mapper.class_.user),
                selectinload(Consultation.prescription_items),
            )
            .order_by(Consultation.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        consultations = list(result.scalars().unique().all())

        queue_items: List[PharmacyPrescriptionQueueItem] = []
        for c in consultations:
            patient_name = c.patient.full_name if c.patient else "Patient"
            patient_phone = c.patient.phone if c.patient else None
            doc_name = c.doctor.user.full_name if (c.doctor and c.doctor.user) else "Doctor"
            room_no = c.doctor.room_number if c.doctor else "Cabin"
            
            items_resp = [
                PrescriptionItemResponse.model_validate(p)
                for p in c.prescription_items
            ]
            all_dispensed = all(p.dispense_status in ["DISPENSED", "OUT_OF_STOCK", "SUBSTITUTED"] for p in c.prescription_items)

            queue_items.append(
                PharmacyPrescriptionQueueItem(
                    consultation_id=c.id,
                    appointment_id=c.appointment_id,
                    patient_id=c.patient_id,
                    patient_name=patient_name,
                    patient_phone=patient_phone,
                    doctor_name=doc_name,
                    room_number=room_no,
                    diagnosis=c.diagnosis,
                    prescribed_at=c.created_at,
                    is_all_dispensed=all_dispensed,
                    items=items_resp,
                )
            )

        return queue_items

    async def dispense_prescription_items(
        self,
        db: AsyncSession,
        pharmacist_id: uuid.UUID,
        consultation_id: uuid.UUID,
        items_in: List[DispenseItemRequest],
    ) -> List[MedicineDispenseRecord]:
        records: List[MedicineDispenseRecord] = []

        for item_req in items_in:
            stmt_item = select(PrescriptionItem).where(
                PrescriptionItem.id == item_req.prescription_item_id,
                PrescriptionItem.consultation_id == consultation_id,
            )
            res_item = await db.execute(stmt_item)
            rx_item = res_item.scalar_one_or_none()
            if not rx_item:
                continue

            rx_item.dispense_status = item_req.status.upper()
            db.add(rx_item)

            dispense_record = MedicineDispenseRecord(
                prescription_item_id=rx_item.id,
                pharmacist_id=pharmacist_id,
                status=item_req.status.upper(),
                notes=item_req.notes,
            )
            db.add(dispense_record)
            records.append(dispense_record)

            # Deduct inventory if in stock and requested
            if item_req.deduct_inventory and item_req.status.upper() == "DISPENSED":
                # Find matching medicine by name prefix
                med = await self.get_medicine_by_name(db, rx_item.medicine_name)
                qty = item_req.quantity_deducted if item_req.quantity_deducted and item_req.quantity_deducted > 0 else 1
                if med and med.stock_quantity >= qty:
                    med.stock_quantity -= qty
                    db.add(med)
                elif med and med.stock_quantity > 0:
                    med.stock_quantity = 0
                    db.add(med)

        await db.commit()
        return records

crud_pharmacy = CRUDPharmacy()
