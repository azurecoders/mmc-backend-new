import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.consultation import PrescriptionItem
    from app.models.user import User

class PharmacyMedicine(Base, TimestampMixin):
    __tablename__ = "pharmacy_medicines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    generic_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # e.g., ANTIBIOTIC, CARDIOVASCULAR
    dosage_form: Mapped[str] = mapped_column(String(50), nullable=False)  # TABLET, CAPSULE, SYRUP, INJECTION
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0.00, nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_level: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<PharmacyMedicine name={self.name} stock={self.stock_quantity}>"

class MedicineDispenseRecord(Base, TimestampMixin):
    __tablename__ = "medicine_dispenses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prescription_items.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    pharmacist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), default="DISPENSED", nullable=False
    )  # DISPENSED, OUT_OF_STOCK, SUBSTITUTED
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # e.g., substitution brand notes
    dispensed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    prescription_item: Mapped["PrescriptionItem"] = relationship("PrescriptionItem", lazy="joined")
    pharmacist: Mapped["User"] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<MedicineDispenseRecord item={self.prescription_item_id} status={self.status}>"
