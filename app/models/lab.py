from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.consultation import Consultation
    from app.models.doctor import DoctorProfile
    from app.models.user import User

class LabTestCatalog(Base, TimestampMixin):
    __tablename__ = "lab_test_catalog"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # e.g., CBC, XRAY_CHEST
    category: Mapped[str] = mapped_column(String(50), index=True, nullable=False)  # HEMATOLOGY, RADIOLOGY, BIOCHEMISTRY, etc.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    standard_turnaround_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<LabTestCatalog code={self.code} name={self.name}>"

class LabOrder(Base, TimestampMixin):
    __tablename__ = "lab_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consultations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lab_test_catalog.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
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

    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    urgency: Mapped[str] = mapped_column(String(20), default="ROUTINE", nullable=False)  # ROUTINE, URGENT, STAT
    
    # Status: ORDERED, SAMPLE_COLLECTED, IN_PROGRESS, COMPLETED, CANCELLED
    status: Mapped[str] = mapped_column(
        String(30), default="ORDERED", index=True, nullable=False
    )
    sample_collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    consultation: Mapped["Consultation"] = relationship("Consultation", back_populates="lab_orders")
    test: Mapped["LabTestCatalog"] = relationship("LabTestCatalog", lazy="joined")
    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id], lazy="joined")
    doctor: Mapped["DoctorProfile"] = relationship("DoctorProfile", foreign_keys=[doctor_id], lazy="joined")
    result: Mapped[Optional["LabResult"]] = relationship("LabResult", back_populates="lab_order", uselist=False, lazy="joined")

    def __repr__(self) -> str:
        return f"<LabOrder id={self.id} test={self.test_id} status={self.status}>"

class LabResult(Base, TimestampMixin):
    __tablename__ = "lab_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    lab_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lab_orders.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    lab_assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    result_summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    report_file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_abnormal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    critical_alert: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    lab_order: Mapped["LabOrder"] = relationship("LabOrder", back_populates="result")
    lab_assistant: Mapped["User"] = relationship("User", foreign_keys=[lab_assistant_id], lazy="joined")

    def __repr__(self) -> str:
        return f"<LabResult id={self.id} order={self.lab_order_id} abnormal={self.is_abnormal}>"
