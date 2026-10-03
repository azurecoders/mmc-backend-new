import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.token import RefreshToken

class CRUDRefreshToken:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, token: str, expires_at: datetime
    ) -> RefreshToken:
        db_obj = RefreshToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at,
            is_revoked=False,
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def get_valid_token(
        self, db: AsyncSession, token: str
    ) -> Optional[RefreshToken]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.token == token,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > now,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, db: AsyncSession, token: str) -> bool:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.token == token)
            .values(is_revoked=True)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0

    async def revoke_all_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)
            .values(is_revoked=True)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount

crud_token = CRUDRefreshToken()
