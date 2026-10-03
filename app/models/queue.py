import uuid
from datetime import date, datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.doctor import DoctorProfile
    from app.models.user import User

class QueueEntry(Base, TimestampMixin):
    __tablename__ = "queue_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    queue_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    
    # Queue Status: WAITING, CALLED_IN, IN_CONSULTATION, ON_HOLD, COMPLETED, NO_SHOW, CANCELLED
    status: Mapped[str] = mapped_column(
        String(30), default="WAITING", index=True, nullable=False
    )
    is_priority: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Timestamps for analytics and wait-time estimations
    check_in_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    called_in_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_end_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Compounder or staff who called / managed turn
    called_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    appointment: Mapped["Appointment"] = relationship("Appointment", lazy="joined")
    doctor: Mapped["DoctorProfile"] = relationship("DoctorProfile", lazy="joined")
    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id], lazy="joined")
    called_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[called_by_user_id], lazy="joined")

    def __repr__(self) -> str:
        return f"<QueueEntry doctor={self.doctor_id} token={self.token_number} status={self.status}>"
