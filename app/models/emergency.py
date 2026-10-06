from datetime import datetime, timezone
import uuid
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.user import User

# Association table between Emergency Code Groups and User Members
emergency_group_members = Table(
    "emergency_group_members",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("emergency_code_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "assigned_at",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    ),
)


class EmergencyCodeGroup(Base, TimestampMixin):
    __tablename__ = "emergency_code_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(20), default="#2563EB", nullable=False)
    badge_color: Mapped[str] = mapped_column(String(20), default="blue", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    call_to_action: Mapped[str] = mapped_column(String(200), default="Immediate response required", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Assigned team members (doctors, nurses, compounders, admins)
    members: Mapped[List["User"]] = relationship(
        "User",
        secondary=emergency_group_members,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<EmergencyCodeGroup code={self.code} name={self.name}>"


class EmergencyAlert(Base, TimestampMixin):
    __tablename__ = "emergency_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emergency_code_groups.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    code_name: Mapped[str] = mapped_column(String(100), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(20), default="#2563EB", nullable=False)
    ward: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    location_details: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    triggered_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Status: ACTIVE, ACKNOWLEDGED, RESOLVED, CANCELLED
    status: Mapped[str] = mapped_column(
        String(30), default="ACTIVE", index=True, nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    group: Mapped["EmergencyCodeGroup"] = relationship("EmergencyCodeGroup", lazy="joined")
    triggered_by: Mapped["User"] = relationship("User", foreign_keys=[triggered_by_id], lazy="joined")
    resolved_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[resolved_by_id], lazy="joined")
    responders: Mapped[List["EmergencyAlertResponder"]] = relationship(
        "EmergencyAlertResponder", back_populates="alert", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EmergencyAlert id={self.id} code={self.code} ward={self.ward} status={self.status}>"


class EmergencyAlertResponder(Base, TimestampMixin):
    __tablename__ = "emergency_alert_responders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emergency_alerts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), default="RESPONDING", nullable=False)
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    alert: Mapped["EmergencyAlert"] = relationship("EmergencyAlert", back_populates="responders")
    user: Mapped["User"] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<EmergencyAlertResponder alert={self.alert_id} user={self.user_id}>"
