import uuid
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, Integer, Numeric, ForeignKey, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.user import User
    from app.models.appointment import Appointment

class DoctorProfile(Base, TimestampMixin):
    __tablename__ = "doctor_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    specialization: Mapped[str] = mapped_column(String(150), nullable=False)
    qualifications: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g., MBBS, MD, FRCS
    experience_years: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consultation_fee: Mapped[float] = mapped_column(Numeric(10, 2), default=0.00, nullable=False)
    room_number: Mapped[str] = mapped_column(String(50), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    avg_consultation_mins: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", lazy="joined")
    department: Mapped["Department"] = relationship("Department", back_populates="doctors", lazy="joined")
    schedules: Mapped[List["DoctorSchedule"]] = relationship(
        "DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan", lazy="selectin"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment", back_populates="doctor"
    )

    def __repr__(self) -> str:
        return f"<DoctorProfile id={self.id} specialization={self.specialization}>"

class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time: Mapped[str] = mapped_column(String(10), nullable=False)  # "09:00"
    end_time: Mapped[str] = mapped_column(String(10), nullable=False)  # "17:00"
    max_daily_patients: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctor: Mapped["DoctorProfile"] = relationship("DoctorProfile", back_populates="schedules")

    def __repr__(self) -> str:
        return f"<DoctorSchedule doctor_id={self.doctor_id} day={self.day_of_week}>"
