from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permissions
from app.crud.crud_permission import crud_permission
from app.schemas.permission import PermissionCreate, PermissionResponse

router = APIRouter()

@router.get(
    "/",
    response_model=List[PermissionResponse],
    summary="List all system permissions",
    dependencies=[Depends(require_permissions(["permissions:read"]))],
)
async def list_permissions(
    db: Annotated[AsyncSession, Depends(get_db)],
    module: Optional[str] = Query(None, description="Filter by module, e.g. APPOINTMENTS, QUEUE, LAB"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    """
    Returns list of granular permissions. Filterable by functional module.
    """
    return await crud_permission.get_multi(db, skip=skip, limit=limit, module=module)

@router.post(
    "/",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new permission dynamically",
    dependencies=[Depends(require_permissions(["permissions:create"]))],
)
async def create_permission(
    permission_in: PermissionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Adds a new dynamic permission to the system without changing code.
    """
    existing = await crud_permission.get_by_code(db, permission_in.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permission with code '{permission_in.code}' already exists.",
        )
    return await crud_permission.create(db, permission_in)
