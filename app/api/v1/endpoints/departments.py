import uuid
from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permissions
from app.crud.crud_department import crud_department
from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate

router = APIRouter()

@router.get(
    "/",
    response_model=List[DepartmentResponse],
    summary="List all hospital departments",
)
async def list_departments(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    active_only: bool = Query(True, description="Only return active departments"),
):
    return await crud_department.get_multi(db, skip=skip, limit=limit, active_only=active_only)

@router.post(
    "/",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new hospital department",
    dependencies=[Depends(require_permissions(["users:create"]))],
)
async def create_department(
    dept_in: DepartmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await crud_department.get_by_code(db, dept_in.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department with code '{dept_in.code}' already exists.",
        )
    return await crud_department.create(db, dept_in)

@router.get(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Get department details",
)
async def get_department(
    department_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    dept = await crud_department.get_by_id(db, department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    return dept

@router.put(
    "/{department_id}",
    response_model=DepartmentResponse,
    summary="Update department details",
    dependencies=[Depends(require_permissions(["users:create"]))],
)
async def update_department(
    department_id: uuid.UUID,
    dept_in: DepartmentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    dept = await crud_department.get_by_id(db, department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    return await crud_department.update(db, db_obj=dept, obj_in=dept_in)
