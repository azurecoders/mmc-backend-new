import uuid
from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permissions
from app.crud.crud_permission import crud_permission
from app.crud.crud_role import crud_role
from app.models.role import Role
from app.schemas.auth import MessageResponse
from app.schemas.role import (
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    RoleWithPermissionsResponse,
)

router = APIRouter()

async def _build_role_details(db: AsyncSession, role: Role) -> RoleWithPermissionsResponse:
    effective_perms = await crud_role.get_effective_permissions(db, role.id)
    return RoleWithPermissionsResponse(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        parent_role_id=role.parent_role_id,
        is_system=role.is_system,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permissions=role.permissions,
        sub_roles=[
            RoleResponse(
                id=sub.id,
                code=sub.code,
                name=sub.name,
                description=sub.description,
                parent_role_id=sub.parent_role_id,
                is_system=sub.is_system,
                created_at=sub.created_at,
                updated_at=sub.updated_at,
            )
            for sub in role.sub_roles
        ],
        effective_permission_codes=sorted(list(effective_perms)),
    )

@router.get(
    "/",
    response_model=List[RoleWithPermissionsResponse],
    summary="List all roles and their sub-roles",
    dependencies=[Depends(require_permissions(["roles:read"]))],
)
async def list_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    """
    Returns all roles, sub-roles, directly assigned permissions, and resolved effective permissions.
    """
    roles = await crud_role.get_multi(db, skip=skip, limit=limit)
    return [await _build_role_details(db, role) for role in roles]

@router.post(
    "/",
    response_model=RoleWithPermissionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new role or sub-role dynamically",
    dependencies=[Depends(require_permissions(["roles:create"]))],
)
async def create_role(
    role_in: RoleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Dynamically creates a new role or sub-role.
    If 'parent_role_id' is supplied, this role acts as a sub-role and inherits all permissions
    from the parent role.
    """
    existing_role = await crud_role.get_by_code(db, role_in.code)
    if existing_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role with code '{role_in.code}' already exists.",
        )

    # Validate parent role if supplied
    if role_in.parent_role_id:
        parent = await crud_role.get_by_id(db, role_in.parent_role_id)
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent role with ID '{role_in.parent_role_id}' not found.",
            )

    # Validate permissions to attach
    permissions = []
    if role_in.permission_codes:
        permissions = await crud_permission.get_by_codes(db, role_in.permission_codes)
        found_codes = {p.code for p in permissions}
        missing_codes = set(role_in.permission_codes) - found_codes
        if missing_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown permission codes: {', '.join(sorted(missing_codes))}",
            )

    role = await crud_role.create(db, obj_in=role_in, permissions=permissions)
    # Refresh with relationships loaded
    loaded_role = await crud_role.get_by_id(db, role.id)
    return await _build_role_details(db, loaded_role)

@router.get(
    "/{role_id}",
    response_model=RoleWithPermissionsResponse,
    summary="Get details of a specific role",
    dependencies=[Depends(require_permissions(["roles:read"]))],
)
async def get_role(
    role_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    role = await crud_role.get_by_id(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    return await _build_role_details(db, role)

@router.put(
    "/{role_id}",
    response_model=RoleWithPermissionsResponse,
    summary="Update role metadata, parent, or permissions",
    dependencies=[Depends(require_permissions(["roles:update"]))],
)
async def update_role(
    role_id: uuid.UUID,
    role_update: RoleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    role = await crud_role.get_by_id(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    # Validate parent if updated
    if role_update.parent_role_id is not None:
        if role_update.parent_role_id == role.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A role cannot be its own parent.",
            )
        parent = await crud_role.get_by_id(db, role_update.parent_role_id)
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Specified parent role does not exist.",
            )

    # Validate permissions if updated
    new_perms = None
    if role_update.permission_codes is not None:
        new_perms = await crud_permission.get_by_codes(db, role_update.permission_codes)
        found_codes = {p.code for p in new_perms}
        missing_codes = set(role_update.permission_codes) - found_codes
        if missing_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown permission codes: {', '.join(sorted(missing_codes))}",
            )

    updated_role = await crud_role.update(
        db, db_obj=role, obj_in=role_update, new_permissions=new_perms
    )
    loaded_role = await crud_role.get_by_id(db, updated_role.id)
    return await _build_role_details(db, loaded_role)

@router.delete(
    "/{role_id}",
    response_model=MessageResponse,
    summary="Delete a custom role",
    dependencies=[Depends(require_permissions(["roles:delete"]))],
)
async def delete_role(
    role_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    role = await crud_role.get_by_id(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"System role '{role.code}' is protected and cannot be deleted.",
        )
    if role.sub_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete this role because it has active sub-roles. Reassign or delete sub-roles first.",
        )

    await crud_role.delete(db, role)
    return MessageResponse(message=f"Role '{role.name}' successfully deleted.")
