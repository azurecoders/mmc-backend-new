import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import sio
from app.crud.crud_lab import crud_lab
from app.models.user import User
from app.schemas.lab import (
    LabOrderResponse,
    LabResultResponse,
    LabResultSubmitRequest,
    LabTestCatalogCreate,
    LabTestCatalogResponse,
)

router = APIRouter()

@router.get(
    "/catalog",
    response_model=List[LabTestCatalogResponse],
    summary="List available laboratory and diagnostic tests",
)
async def list_lab_catalog(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = Query(None, description="Filter by category e.g. HEMATOLOGY, RADIOLOGY"),
    active_only: bool = Query(True),
):
    return await crud_lab.get_catalog(db, category=category, active_only=active_only)

@router.post(
    "/catalog",
    response_model=LabTestCatalogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Lab assistant adds a new diagnostic test to hospital catalog",
    dependencies=[Depends(require_permissions(["lab:manage_catalog"]))],
)
async def create_lab_test(
    test_in: LabTestCatalogCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await crud_lab.get_test_by_code(db, test_in.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lab test with code '{test_in.code}' already exists.",
        )
    return await crud_lab.create_test(db, obj_in=test_in)

@router.get(
    "/orders",
    response_model=List[LabOrderResponse],
    summary="List lab test orders",
    dependencies=[Depends(require_permissions(["lab:read_orders"]))],
)
async def list_lab_orders(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    patient_id: Optional[uuid.UUID] = Query(None),
    doctor_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    user_roles = {r.code for r in current_user.roles}
    if "PATIENT" in user_roles and "SUPER_ADMIN" not in user_roles and "LAB_ASSISTANT" not in user_roles and "DOCTOR" not in user_roles:
        patient_id = current_user.id

    return await crud_lab.get_orders(
        db, skip=skip, limit=limit, patient_id=patient_id, doctor_id=doctor_id, status=status
    )

@router.get(
    "/orders/{order_id}",
    response_model=LabOrderResponse,
    summary="Get lab order details and test results",
    dependencies=[Depends(require_permissions(["lab:read_orders"]))],
)
async def get_lab_order(
    order_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    order = await crud_lab.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab order not found.",
        )
    return order

@router.post(
    "/orders/{order_id}/collect-sample",
    response_model=LabOrderResponse,
    summary="Lab assistant marks sample collected",
    dependencies=[Depends(require_permissions(["lab:upload_result"]))],
)
async def collect_sample(
    order_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    order = await crud_lab.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab order not found.",
        )
    return await crud_lab.collect_sample(db, order=order)

@router.post(
    "/orders/{order_id}/submit-result",
    response_model=LabResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Lab assistant submits test findings and diagnostic report",
    dependencies=[Depends(require_permissions(["lab:upload_result"]))],
)
async def submit_lab_result(
    order_id: uuid.UUID,
    result_in: LabResultSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    order = await crud_lab.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lab order not found.",
        )
    if order.status == "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Results have already been submitted for this lab order.",
        )

    lab_result = await crud_lab.submit_result(
        db, order=order, lab_assistant_id=current_user.id, obj_in=result_in
    )

    # Real-time notification to Doctor & Patient
    report_alert = {
        "order_id": str(order.id),
        "consultation_id": str(order.consultation_id),
        "test_name": order.test.name if order.test else "Diagnostic Test",
        "result_summary": lab_result.result_summary,
        "is_abnormal": lab_result.is_abnormal,
        "critical_alert": lab_result.critical_alert,
        "completed_at": str(lab_result.completed_at),
        "message": f"Lab report ready: {order.test.name if order.test else 'Test'}",
    }
    await sio.emit("lab:report_completed", report_alert, room=f"patient:{order.patient_id}")
    await sio.emit("lab:report_completed", report_alert, room=f"doctor:{order.doctor_id}")

    return lab_result
