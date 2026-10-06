from datetime import datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.models.emergency import EmergencyCodeGroup, EmergencyAlert, EmergencyAlertResponder, emergency_group_members
from app.models.user import User

class CRUDEmergency:
    async def get_groups(self, db: AsyncSession, active_only: bool = True) -> List[EmergencyCodeGroup]:
        stmt = (
            select(EmergencyCodeGroup)
            .options(selectinload(EmergencyCodeGroup.members).selectinload(User.roles))
            .order_by(EmergencyCodeGroup.code)
        )
        if active_only:
            stmt = stmt.where(EmergencyCodeGroup.is_active == True)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_group_by_code(self, db: AsyncSession, code: str) -> Optional[EmergencyCodeGroup]:
        stmt = (
            select(EmergencyCodeGroup)
            .where(EmergencyCodeGroup.code == code.upper().strip())
            .options(selectinload(EmergencyCodeGroup.members).selectinload(User.roles))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_member_to_group(
        self, db: AsyncSession, group: EmergencyCodeGroup, user: User
    ) -> EmergencyCodeGroup:
        if user not in group.members:
            group.members.append(user)
            db.add(group)
            await db.commit()
            await db.refresh(group)
        return group

    async def remove_member_from_group(
        self, db: AsyncSession, group: EmergencyCodeGroup, user: User
    ) -> EmergencyCodeGroup:
        if user in group.members:
            group.members.remove(user)
            db.add(group)
            await db.commit()
            await db.refresh(group)
        return group

    async def create_alert(
        self,
        db: AsyncSession,
        group: EmergencyCodeGroup,
        ward: str,
        triggered_by: User,
        location_details: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> EmergencyAlert:
        alert_id = uuid.uuid4()
        alert = EmergencyAlert(
            id=alert_id,
            group_id=group.id,
            code=group.code,
            code_name=group.name,
            color_hex=group.color_hex,
            ward=ward.strip(),
            location_details=location_details.strip() if location_details else None,
            notes=notes.strip() if notes else None,
            triggered_by_id=triggered_by.id,
            status="ACTIVE",
            triggered_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        await db.commit()
        return await self.get_alert_by_id(db, alert_id) # type: ignore

    async def get_alert_by_id(self, db: AsyncSession, alert_id: uuid.UUID) -> Optional[EmergencyAlert]:
        stmt = (
            select(EmergencyAlert)
            .where(EmergencyAlert.id == alert_id)
            .options(
                joinedload(EmergencyAlert.group).selectinload(EmergencyCodeGroup.members),
                joinedload(EmergencyAlert.triggered_by),
                joinedload(EmergencyAlert.resolved_by),
                selectinload(EmergencyAlert.responders).joinedload(EmergencyAlertResponder.user),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_alerts(self, db: AsyncSession) -> List[EmergencyAlert]:
        stmt = (
            select(EmergencyAlert)
            .where(EmergencyAlert.status.in_(["ACTIVE", "ACKNOWLEDGED"]))
            .options(
                joinedload(EmergencyAlert.group).selectinload(EmergencyCodeGroup.members),
                joinedload(EmergencyAlert.triggered_by),
                joinedload(EmergencyAlert.resolved_by),
                selectinload(EmergencyAlert.responders).joinedload(EmergencyAlertResponder.user),
            )
            .order_by(EmergencyAlert.triggered_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge_alert(
        self, db: AsyncSession, alert: EmergencyAlert, user: User, note: Optional[str] = None
    ) -> EmergencyAlert:
        # Check if already responded
        stmt = select(EmergencyAlertResponder).where(
            and_(EmergencyAlertResponder.alert_id == alert.id, EmergencyAlertResponder.user_id == user.id)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            responder = EmergencyAlertResponder(
                alert_id=alert.id,
                user_id=user.id,
                status="RESPONDING",
                responded_at=datetime.now(timezone.utc),
                note=note.strip() if note else None,
            )
            db.add(responder)

        if alert.status == "ACTIVE":
            alert.status = "ACKNOWLEDGED"
            db.add(alert)

        alert_id = alert.id
        await db.commit()
        db.expire_all()
        return await self.get_alert_by_id(db, alert_id) # type: ignore

    async def resolve_alert(
        self, db: AsyncSession, alert: EmergencyAlert, user: User, resolution_notes: Optional[str] = None
    ) -> EmergencyAlert:
        alert_id = alert.id
        alert.status = "RESOLVED"
        alert.resolved_at = datetime.now(timezone.utc)
        alert.resolved_by_id = user.id
        alert.resolution_notes = resolution_notes.strip() if resolution_notes else "Resolved on scene"
        db.add(alert)
        await db.commit()
        db.expire_all()
        return await self.get_alert_by_id(db, alert_id) # type: ignore

crud_emergency = CRUDEmergency()
