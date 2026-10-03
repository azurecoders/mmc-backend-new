import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import sio, socket_manager
from app.crud.crud_consultation import crud_consultation
from app.crud.crud_pharmacy import crud_pharmacy
from app.models.user import User
from app.schemas.pharmacy import (
    MedicineDispenseRecordResponse,
    PharmacyMedicineCreate,
    PharmacyMedicineResponse,
    PharmacyMedicineUpdate,
    PharmacyPrescriptionQueueItem,
    PrescriptionDispenseBatchRequest,
)

router = APIRouter()

@router.get(
    "/inventory",
    response_model=List[PharmacyMedicineResponse],
    summary="List pharmacy drug inventory and stock levels",
    dependencies=[Depends(require_permissions(["pharmacy:read_inventory"]))],
)
async def list_inventory(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = Query(None, description="Filter by category e.g. ANTIBIOTIC, CARDIOVASCULAR"),
    search: Optional[str] = Query(None, description="Search medicine name or generic salt"),
    low_stock_only: bool = Query(False, description="Filter medicines at or below reorder level"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return await crud_pharmacy.get_inventory(
        db, skip=skip, limit=limit, category=category, search=search, low_stock_only=low_stock_only
    )

@router.post(
    "/inventory",
    response_model=PharmacyMedicineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new medicine to pharmacy inventory",
    dependencies=[Depends(require_permissions(["pharmacy:manage_inventory"]))],
)
async def add_medicine(
    medicine_in: PharmacyMedicineCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await crud_pharmacy.get_medicine_by_name(db, medicine_in.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Medicine '{medicine_in.name}' already exists in inventory.",
        )
    return await crud_pharmacy.create_medicine(db, medicine_in)

@router.put(
    "/inventory/{medicine_id}",
    response_model=PharmacyMedicineResponse,
    summary="Update medicine stock quantity, pricing, or details",
    dependencies=[Depends(require_permissions(["pharmacy:manage_inventory"]))],
)
async def update_medicine(
    medicine_id: uuid.UUID,
    medicine_update: PharmacyMedicineUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    med = await crud_pharmacy.get_medicine_by_id(db, medicine_id)
    if not med:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medicine not found in inventory.",
        )
    return await crud_pharmacy.update_medicine(db, db_obj=med, obj_in=medicine_update)

@router.get(
    "/prescriptions",
    response_model=List[PharmacyPrescriptionQueueItem],
    summary="Pharmacist view of incoming prescriptions to dispense",
    dependencies=[Depends(require_permissions(["prescriptions:read"]))],
)
async def list_prescription_queue(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await crud_pharmacy.get_prescription_queue(db, skip=skip, limit=limit)

@router.post(
    "/dispense",
    response_model=List[MedicineDispenseRecordResponse],
    summary="Pharmacist dispenses medicines and updates stock",
    dependencies=[Depends(require_permissions(["pharmacy:dispense"]))],
)
async def dispense_medicines(
    dispense_in: PrescriptionDispenseBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Pharmacist processes and dispenses items from a prescription.
    Automatically deducts inventory stock and notifies the patient device via Socket.IO.
    """
    consultation = await crud_consultation.get_by_id(db, dispense_in.consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation record not found.",
        )

    records = await crud_pharmacy.dispense_prescription_items(
        db,
        pharmacist_id=current_user.id,
        consultation_id=dispense_in.consultation_id,
        items_in=dispense_in.items,
    )

    # Real-time alert to patient
    counter = dispense_in.counter_name or "Pharmacy Counter #1"
    patient_alert = {
        "consultation_id": str(consultation.id),
        "appointment_id": str(consultation.appointment_id),
        "message": f"Your prescribed medications have been prepared and are ready for pickup at {counter}.",
        "counter": counter,
        "items_dispensed_count": len(records),
    }
    await sio.emit("pharmacy:prescription_dispensed", patient_alert, room=f"patient:{consultation.patient_id}")
    await sio.emit("pharmacy:prescription_dispensed", patient_alert, room=f"appointment:{consultation.appointment_id}")

    return records
