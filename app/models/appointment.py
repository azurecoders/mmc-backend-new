import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.doctor import DoctorProfile

class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    appointment_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doctor_profiles.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    booking_type: Mapped[str] = mapped_column(
        String(20), default="ONLINE", index=True, nullable=False
    )  # "ONLINE", "WALK_IN"
    
    appointment_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    slot_time: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g., "10:00"
    token_number: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    symptom_duration: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # MILD, MODERATE, SEVERE
    
    # AI Recommendation Metadata
    ai_recommended_department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ai_recommendation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status & Verification
    status: Mapped[str] = mapped_column(
        String(30), default="PENDING_APPROVAL", index=True, nullable=False
    )  # PENDING_APPROVAL, APPROVED, CHECKED_IN, COMPLETED, CANCELLED, REJECTED
    
    verified_by_compounder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id], lazy="joined")
    doctor: Mapped["DoctorProfile"] = relationship("DoctorProfile", foreign_keys=[doctor_id], back_populates="appointments", lazy="joined")
    verified_by_compounder: Mapped[Optional["User"]] = relationship("User", foreign_keys=[verified_by_compounder_id], lazy="joined")

    def __repr__(self) -> str:
        return f"<Appointment {self.appointment_number} token={self.token_number} status={self.status}>"
