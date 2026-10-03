import uuid
from typing import List, Optional, Set
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.security import hash_password, verify_password
from app.crud.crud_role import crud_role
from app.models.user import User
from app.models.role import Role
from app.schemas.user import UserCreate, UserUpdate

class CRUDUser:
    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.roles).selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.email == email.lower().strip())
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.roles).selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, db: AsyncSession, phone: str) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.phone == phone.strip())
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.roles).selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_identifier(
        self, db: AsyncSession, identifier: str
    ) -> Optional[User]:
        """Lookup user by email OR phone number."""
        clean_ident = identifier.strip()
        stmt = (
            select(User)
            .where(
                or_(
                    User.email == clean_ident.lower(),
                    User.phone == clean_ident,
                )
            )
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.roles).selectinload(Role.parent_role),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        role_code: Optional[str] = None,
    ) -> List[User]:
        stmt = (
            select(User)
            .offset(skip)
            .limit(limit)
            .order_by(User.created_at.desc())
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
            )
        )
        if search:
            search_pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(search_pattern),
                    User.full_name.ilike(search_pattern),
                    User.phone.ilike(search_pattern),
                )
            )
        if role_code:
            stmt = stmt.join(User.roles).where(Role.code == role_code.upper())

        result = await db.execute(stmt)
        return list(result.scalars().unique().all())

    async def create(
        self, db: AsyncSession, obj_in: UserCreate, roles: List[Role] = []
    ) -> User:
        user = User(
            email=obj_in.email.lower().strip(),
            phone=obj_in.phone.strip() if obj_in.phone else None,
            full_name=obj_in.full_name.strip(),
            hashed_password=hash_password(obj_in.password),
            is_active=True,
            is_verified=False,
            roles=roles,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def update(
        self, db: AsyncSession, db_obj: User, obj_in: UserUpdate
    ) -> User:
        if obj_in.full_name is not None:
            db_obj.full_name = obj_in.full_name.strip()
        if obj_in.phone is not None:
            db_obj.phone = obj_in.phone.strip() if obj_in.phone else None
        if obj_in.is_active is not None:
            db_obj.is_active = obj_in.is_active
        if obj_in.is_verified is not None:
            db_obj.is_verified = obj_in.is_verified

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def set_roles(
        self, db: AsyncSession, db_obj: User, roles: List[Role]
    ) -> User:
        db_obj.roles = roles
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update_password(
        self, db: AsyncSession, db_obj: User, new_password: str
    ) -> User:
        db_obj.hashed_password = hash_password(new_password)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def get_effective_permissions(
        self, db: AsyncSession, user: User
    ) -> Set[str]:
        """
        Calculates all effective permissions for a user across all their assigned roles
        and all parent roles inherited through hierarchy.
        """
        all_permissions: Set[str] = set()

        for role in user.roles:
            if role.code == "SUPER_ADMIN":
                all_permissions.add("*")
            # Collect permissions from this role and any parent roles recursively
            role_perms = await crud_role.get_effective_permissions(db, role.id)
            all_permissions.update(role_perms)

        return all_permissions

crud_user = CRUDUser()
