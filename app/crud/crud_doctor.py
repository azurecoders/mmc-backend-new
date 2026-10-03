import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from app.models.doctor import DoctorProfile, DoctorSchedule
from app.schemas.doctor import DoctorProfileCreate, DoctorProfileUpdate, DoctorScheduleCreate

class CRUDDoctor:
    async def get_by_id(self, db: AsyncSession, doctor_id: uuid.UUID) -> Optional[DoctorProfile]:
        stmt = (
            select(DoctorProfile)
            .where(DoctorProfile.id == doctor_id)
            .options(
                joinedload(DoctorProfile.user),
                joinedload(DoctorProfile.department),
                selectinload(DoctorProfile.schedules),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[DoctorProfile]:
        stmt = (
            select(DoctorProfile)
            .where(DoctorProfile.user_id == user_id)
            .options(
                joinedload(DoctorProfile.user),
                joinedload(DoctorProfile.department),
                selectinload(DoctorProfile.schedules),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        department_id: Optional[uuid.UUID] = None,
        available_only: bool = False,
    ) -> List[DoctorProfile]:
        stmt = (
            select(DoctorProfile)
            .options(
                joinedload(DoctorProfile.user),
                joinedload(DoctorProfile.department),
                selectinload(DoctorProfile.schedules),
            )
            .offset(skip)
            .limit(limit)
        )
        if department_id:
            stmt = stmt.where(DoctorProfile.department_id == department_id)
        if available_only:
            stmt = stmt.where(DoctorProfile.is_available == True)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self, db: AsyncSession, obj_in: DoctorProfileCreate
    ) -> DoctorProfile:
        doctor = DoctorProfile(
            user_id=obj_in.user_id,
            department_id=obj_in.department_id,
            specialization=obj_in.specialization.strip(),
            qualifications=obj_in.qualifications.strip(),
            experience_years=obj_in.experience_years,
            consultation_fee=obj_in.consultation_fee,
            room_number=obj_in.room_number.strip(),
            bio=obj_in.bio,
            is_available=obj_in.is_available,
            avg_consultation_mins=obj_in.avg_consultation_mins,
        )
        db.add(doctor)
        await db.flush()

        if obj_in.schedules:
            for sch in obj_in.schedules:
                schedule_obj = DoctorSchedule(
                    doctor_id=doctor.id,
                    day_of_week=sch.day_of_week,
                    start_time=sch.start_time,
                    end_time=sch.end_time,
                    max_daily_patients=sch.max_daily_patients,
                    is_active=sch.is_active,
                )
                db.add(schedule_obj)

        await db.commit()
        return await self.get_by_id(db, doctor.id)

    async def update(
        self, db: AsyncSession, db_obj: DoctorProfile, obj_in: DoctorProfileUpdate
    ) -> DoctorProfile:
        if obj_in.specialization is not None:
            db_obj.specialization = obj_in.specialization.strip()
        if obj_in.qualifications is not None:
            db_obj.qualifications = obj_in.qualifications.strip()
        if obj_in.experience_years is not None:
            db_obj.experience_years = obj_in.experience_years
        if obj_in.consultation_fee is not None:
            db_obj.consultation_fee = obj_in.consultation_fee
        if obj_in.room_number is not None:
            db_obj.room_number = obj_in.room_number.strip()
        if obj_in.bio is not None:
            db_obj.bio = obj_in.bio
        if obj_in.is_available is not None:
            db_obj.is_available = obj_in.is_available
        if obj_in.avg_consultation_mins is not None:
            db_obj.avg_consultation_mins = obj_in.avg_consultation_mins
        if obj_in.department_id is not None:
            db_obj.department_id = obj_in.department_id

        db.add(db_obj)
        await db.commit()
        return await self.get_by_id(db, db_obj.id)

    async def add_schedule(
        self, db: AsyncSession, doctor_id: uuid.UUID, obj_in: DoctorScheduleCreate
    ) -> DoctorSchedule:
        schedule = DoctorSchedule(
            doctor_id=doctor_id,
            day_of_week=obj_in.day_of_week,
            start_time=obj_in.start_time,
            end_time=obj_in.end_time,
            max_daily_patients=obj_in.max_daily_patients,
            is_active=obj_in.is_active,
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)
        return schedule

crud_doctor = CRUDDoctor()
