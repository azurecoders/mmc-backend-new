import uuid
from datetime import date, datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.doctor import DoctorProfile
    from app.models.user import User

class Consultation(Base, TimestampMixin):
    __tablename__ = "consultations"

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
        ForeignKey("doctor_profiles.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[str] = mapped_column(String(255), nullable=False)  # Provisional / Final diagnosis
    clinical_notes: Mapped[str] = mapped_column(Text, nullable=False)  # Doctor's assessment and findings
    special_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Dietary, lifestyle, rest
    highlights: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Key alerts / red flags
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    appointment: Mapped["Appointment"] = relationship("Appointment", lazy="joined")
    doctor: Mapped["DoctorProfile"] = relationship("DoctorProfile", lazy="joined")
    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id], lazy="joined")
    
    prescription_items: Mapped[List["PrescriptionItem"]] = relationship(
        "PrescriptionItem",
        back_populates="consultation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    lab_orders: Mapped[List["LabOrder"]] = relationship(
        "LabOrder",
        back_populates="consultation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Consultation id={self.id} doctor={self.doctor_id} diagnosis={self.diagnosis}>"

class PrescriptionItem(Base, TimestampMixin):
    __tablename__ = "prescription_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consultations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    medicine_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dosage: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "500mg", "1 tablet"
    frequency: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "1-0-1", "Once daily after food"
    duration: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "5 days", "1 month"
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # e.g., "Before food", "Take with water"
    dispense_status: Mapped[str] = mapped_column(
        String(30), default="PENDING", index=True, nullable=False
    )  # PENDING, DISPENSED, OUT_OF_STOCK, SUBSTITUTED

    consultation: Mapped["Consultation"] = relationship(
        "Consultation", back_populates="prescription_items"
    )

    def __repr__(self) -> str:
        return f"<PrescriptionItem medicine={self.medicine_name} dosage={self.dosage}>"
