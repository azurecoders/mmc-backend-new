import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.department import Department
from app.schemas.department import DepartmentCreate, DepartmentUpdate

class CRUDDepartment:
    async def get_by_id(self, db: AsyncSession, department_id: uuid.UUID) -> Optional[Department]:
        stmt = select(Department).where(Department.id == department_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[Department]:
        stmt = select(Department).where(Department.code == code.upper().strip())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self, db: AsyncSession, skip: int = 0, limit: int = 100, active_only: bool = True
    ) -> List[Department]:
        stmt = select(Department)
        if active_only:
            stmt = stmt.where(Department.is_active == True)
        stmt = stmt.offset(skip).limit(limit).order_by(Department.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, obj_in: DepartmentCreate) -> Department:
        dept = Department(
            name=obj_in.name.strip(),
            code=obj_in.code.upper().strip(),
            description=obj_in.description,
            is_active=obj_in.is_active,
        )
        db.add(dept)
        await db.commit()
        await db.refresh(dept)
        return dept

    async def update(
        self, db: AsyncSession, db_obj: Department, obj_in: DepartmentUpdate
    ) -> Department:
        if obj_in.name is not None:
            db_obj.name = obj_in.name.strip()
        if obj_in.description is not None:
            db_obj.description = obj_in.description
        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

crud_department = CRUDDepartment()
