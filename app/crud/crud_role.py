import uuid
from typing import List, Optional, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.role import Role
from app.models.permission import Permission
from app.schemas.role import RoleCreate, RoleUpdate

class CRUDRole:
    async def get_by_id(self, db: AsyncSession, role_id: uuid.UUID) -> Optional[Role]:
        stmt = (
            select(Role)
            .where(Role.id == role_id)
            .options(
                selectinload(Role.permissions),
                selectinload(Role.sub_roles),
                selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[Role]:
        stmt = (
            select(Role)
            .where(Role.code == code.upper())
            .options(
                selectinload(Role.permissions),
                selectinload(Role.sub_roles),
                selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_codes(self, db: AsyncSession, codes: List[str]) -> List[Role]:
        if not codes:
            return []
        codes_upper = [c.upper() for c in codes]
        stmt = (
            select(Role)
            .where(Role.code.in_(codes_upper))
            .options(
                selectinload(Role.permissions),
                selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_multi(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Role]:
        stmt = (
            select(Role)
            .offset(skip)
            .limit(limit)
            .order_by(Role.name)
            .options(
                selectinload(Role.permissions),
                selectinload(Role.sub_roles),
                selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self, db: AsyncSession, obj_in: RoleCreate, permissions: List[Permission] = []
    ) -> Role:
        role = Role(
            code=obj_in.code.strip().upper(),
            name=obj_in.name.strip(),
            description=obj_in.description,
            parent_role_id=obj_in.parent_role_id,
            is_system=False,
            permissions=permissions,
        )
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    async def update(
        self,
        db: AsyncSession,
        db_obj: Role,
        obj_in: RoleUpdate,
        new_permissions: Optional[List[Permission]] = None,
    ) -> Role:
        if obj_in.name is not None:
            db_obj.name = obj_in.name.strip()
        if obj_in.description is not None:
            db_obj.description = obj_in.description
        if obj_in.parent_role_id is not None:
            # Prevent circular reference
            if obj_in.parent_role_id == db_obj.id:
                raise ValueError("A role cannot be its own parent")
            db_obj.parent_role_id = obj_in.parent_role_id
            
        if new_permissions is not None:
            db_obj.permissions = new_permissions

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, db_obj: Role) -> None:
        await db.delete(db_obj)
        await db.commit()

    async def get_effective_permissions(
        self, db: AsyncSession, role_id: uuid.UUID
    ) -> Set[str]:
        """
        Recursively walk up parent roles and collect all granted permission codes.
        """
        permission_codes: Set[str] = set()
        visited_role_ids: Set[uuid.UUID] = set()

        current_id: Optional[uuid.UUID] = role_id
        while current_id and current_id not in visited_role_ids:
            visited_role_ids.add(current_id)
            current_role = await self.get_by_id(db, current_id)
            if not current_role:
                break
            for perm in current_role.permissions:
                permission_codes.add(perm.code)
            current_id = current_role.parent_role_id

        return permission_codes

crud_role = CRUDRole()
