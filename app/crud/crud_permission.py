import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.permission import Permission
from app.schemas.permission import PermissionCreate

class CRUDPermission:
    async def get_by_id(self, db: AsyncSession, permission_id: uuid.UUID) -> Optional[Permission]:
        stmt = select(Permission).where(Permission.id == permission_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[Permission]:
        stmt = select(Permission).where(Permission.code == code)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_codes(self, db: AsyncSession, codes: List[str]) -> List[Permission]:
        if not codes:
            return []
        stmt = select(Permission).where(Permission.code.in_(codes))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_multi(
        self, db: AsyncSession, skip: int = 0, limit: int = 200, module: Optional[str] = None
    ) -> List[Permission]:
        stmt = select(Permission)
        if module:
            stmt = stmt.where(Permission.module == module.upper())
        stmt = stmt.offset(skip).limit(limit).order_by(Permission.module, Permission.code)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, obj_in: PermissionCreate) -> Permission:
        permission = Permission(
            code=obj_in.code.strip(),
            name=obj_in.name.strip(),
            module=obj_in.module.strip().upper(),
            description=obj_in.description,
        )
        db.add(permission)
        await db.commit()
        await db.refresh(permission)
        return permission

crud_permission = CRUDPermission()
