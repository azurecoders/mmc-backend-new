import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permissions
from app.crud.crud_role import crud_role
from app.crud.crud_user import crud_user
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.user import (
    RoleResponse,
    UserAssignRoles,
    UserCreate,
    UserStaffCreate,
    UserUpdate,
    UserWithRolesResponse,
)

router = APIRouter()

async def _build_user_details(db: AsyncSession, user: User) -> UserWithRolesResponse:
    effective_perms = await crud_user.get_effective_permissions(db, user)
    return UserWithRolesResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        roles=[
            RoleResponse(
                id=role.id,
                code=role.code,
                name=role.name,
                description=role.description,
                parent_role_id=role.parent_role_id,
                is_system=role.is_system,
                created_at=role.created_at,
                updated_at=role.updated_at,
            )
            for role in user.roles
        ],
        permissions=sorted(list(effective_perms)),
    )

@router.get(
    "/",
    response_model=List[UserWithRolesResponse],
    summary="List hospital users and staff",
    dependencies=[Depends(require_permissions(["users:read"]))],
)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    role_code: Optional[str] = Query(None, description="Filter by role code (e.g. DOCTOR, COMPOUNDER)"),
):
    users = await crud_user.get_multi(
        db, skip=skip, limit=limit, search=search, role_code=role_code
    )
    return [await _build_user_details(db, u) for u in users]

@router.post(
    "/",
    response_model=UserWithRolesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new staff or user with designated roles",
    dependencies=[Depends(require_permissions(["users:create"]))],
)
async def create_user(
    user_in: UserStaffCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Creates a user/staff member with explicitly assigned roles (e.g., Doctor, Compounder, Pharmacist, Lab Assistant, or custom roles).
    """
    existing_user = await crud_user.get_by_email(db, user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )
    if user_in.phone:
        existing_phone = await crud_user.get_by_phone(db, user_in.phone)
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this phone number already exists.",
            )

    # Fetch and validate requested roles
    roles = await crud_role.get_by_codes(db, user_in.role_codes)
    found_codes = {r.code for r in roles}
    missing_codes = set(user_in.role_codes) - found_codes
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role codes: {', '.join(sorted(missing_codes))}",
        )

    base_user_in = UserCreate(
        email=user_in.email,
        phone=user_in.phone,
        full_name=user_in.full_name,
        password=user_in.password,
    )
    user = await crud_user.create(db, obj_in=base_user_in, roles=roles)
    loaded_user = await crud_user.get_by_id(db, user.id)
    return await _build_user_details(db, loaded_user)

@router.get(
    "/{user_id}",
    response_model=UserWithRolesResponse,
    summary="Get user details and permissions by ID",
    dependencies=[Depends(require_permissions(["users:read"]))],
)
async def get_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await crud_user.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return await _build_user_details(db, user)

@router.put(
    "/{user_id}",
    response_model=UserWithRolesResponse,
    summary="Update user profile information",
    dependencies=[Depends(require_permissions(["users:update"]))],
)
async def update_user(
    user_id: uuid.UUID,
    user_update: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await crud_user.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user_update.phone and user_update.phone != user.phone:
        existing_phone = await crud_user.get_by_phone(db, user_update.phone)
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this phone number already exists.",
            )

    updated_user = await crud_user.update(db, db_obj=user, obj_in=user_update)
    loaded_user = await crud_user.get_by_id(db, updated_user.id)
    return await _build_user_details(db, loaded_user)

@router.put(
    "/{user_id}/roles",
    response_model=UserWithRolesResponse,
    summary="Assign or update roles for a user dynamically",
    dependencies=[Depends(require_permissions(["roles:assign"]))],
)
async def assign_user_roles(
    user_id: uuid.UUID,
    roles_in: UserAssignRoles,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Dynamically modifies the roles attached to any user account.
    """
    user = await crud_user.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Validate roles
    roles = await crud_role.get_by_codes(db, roles_in.role_codes)
    found_codes = {r.code for r in roles}
    missing_codes = set(roles_in.role_codes) - found_codes
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role codes: {', '.join(sorted(missing_codes))}",
        )

    await crud_user.set_roles(db, db_obj=user, roles=roles)
    loaded_user = await crud_user.get_by_id(db, user.id)
    return await _build_user_details(db, loaded_user)
