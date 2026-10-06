from datetime import datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models.lab import LabOrder, LabResult, LabTestCatalog
from app.schemas.lab import LabResultSubmitRequest, LabTestCatalogCreate

class CRUDLab:
    async def get_test_by_id(self, db: AsyncSession, test_id: uuid.UUID) -> Optional[LabTestCatalog]:
        stmt = select(LabTestCatalog).where(LabTestCatalog.id == test_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_test_by_code(self, db: AsyncSession, code: str) -> Optional[LabTestCatalog]:
        stmt = select(LabTestCatalog).where(LabTestCatalog.code == code.upper().strip())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_catalog(
        self, db: AsyncSession, category: Optional[str] = None, active_only: bool = True
    ) -> List[LabTestCatalog]:
        stmt = select(LabTestCatalog)
        if active_only:
            stmt = stmt.where(LabTestCatalog.is_active == True)
        if category:
            stmt = stmt.where(LabTestCatalog.category == category.upper())
        stmt = stmt.order_by(LabTestCatalog.category, LabTestCatalog.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_test(self, db: AsyncSession, obj_in: LabTestCatalogCreate) -> LabTestCatalog:
        test = LabTestCatalog(
            name=obj_in.name.strip(),
            code=obj_in.code.upper().strip(),
            category=obj_in.category.upper().strip(),
            description=obj_in.description,
            standard_turnaround_hours=obj_in.standard_turnaround_hours,
            is_active=obj_in.is_active,
        )
        db.add(test)
        await db.commit()
        await db.refresh(test)
        return test

    async def get_order_by_id(self, db: AsyncSession, order_id: uuid.UUID) -> Optional[LabOrder]:
        stmt = (
            select(LabOrder)
            .where(LabOrder.id == order_id)
            .options(
                joinedload(LabOrder.test),
                joinedload(LabOrder.patient),
                joinedload(LabOrder.doctor),
                joinedload(LabOrder.consultation),
                joinedload(LabOrder.result).joinedload(LabResult.lab_assistant),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_orders(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        patient_id: Optional[uuid.UUID] = None,
        doctor_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
    ) -> List[LabOrder]:
        stmt = (
            select(LabOrder)
            .options(
                joinedload(LabOrder.test),
                joinedload(LabOrder.patient),
                joinedload(LabOrder.doctor),
                joinedload(LabOrder.result).joinedload(LabResult.lab_assistant),
            )
            .order_by(LabOrder.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        if patient_id:
            stmt = stmt.where(LabOrder.patient_id == patient_id)
        if doctor_id:
            stmt = stmt.where(LabOrder.doctor_id == doctor_id)
        if status:
            stmt = stmt.where(LabOrder.status == status.upper())

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def collect_sample(self, db: AsyncSession, order: LabOrder) -> LabOrder:
        order.status = "SAMPLE_COLLECTED"
        order.sample_collected_at = datetime.now(timezone.utc)
        db.add(order)
        await db.commit()
        return await self.get_order_by_id(db, order.id)

    async def submit_result(
        self,
        db: AsyncSession,
        order: LabOrder,
        lab_assistant_id: uuid.UUID,
        obj_in: LabResultSubmitRequest,
    ) -> LabResult:
        now = datetime.now(timezone.utc)
        result = LabResult(
            lab_order_id=order.id,
            lab_assistant_id=lab_assistant_id,
            result_summary=obj_in.result_summary.strip(),
            findings_json=obj_in.findings_json,
            report_file_url=obj_in.report_file_url,
            is_abnormal=obj_in.is_abnormal,
            critical_alert=obj_in.critical_alert,
            completed_at=now,
        )
        db.add(result)

        order.status = "COMPLETED"
        db.add(order)

        await db.commit()
        await db.refresh(result)
        return result

crud_lab = CRUDLab()
