from datetime import datetime, timezone, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.crud.crud_role import crud_role
from app.crud.crud_token import crud_token
from app.crud.crud_user import crud_user
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserWithRolesResponse, RoleResponse

router = APIRouter()

async def _build_user_response(db: AsyncSession, user: User) -> UserWithRolesResponse:
    effective_perms = await crud_user.get_effective_permissions(db, user)
    roles_response = [
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
    ]
    return UserWithRolesResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        roles=roles_response,
        permissions=sorted(list(effective_perms)),
    )

@router.post(
    "/register",
    response_model=UserWithRolesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient account",
)
async def register(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Public registration endpoint. New users are assigned the 'PATIENT' role by default.
    """
    # Check if user already exists
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

    # Attach default 'PATIENT' role
    patient_role = await crud_role.get_by_code(db, "PATIENT")
    roles = [patient_role] if patient_role else []

    user = await crud_user.create(db, obj_in=user_in, roles=roles)
    return await _build_user_response(db, user)

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email/phone and password",
)
async def login(
    login_in: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Authenticates user with email or phone + password.
    Returns access token, refresh token, user profile, roles, and effective permissions.
    """
    user = await crud_user.get_by_identifier(db, login_in.username_or_email)
    if not user or not verify_password(login_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/phone or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is deactivated. Please contact administration.",
        )

    # Generate JWT tokens
    user_roles_list = [r.code for r in user.roles]
    access_token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email, "roles": user_roles_list},
    )
    refresh_token_str = create_refresh_token(subject=str(user.id))

    # Persist refresh token in DB
    refresh_expiry = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    await crud_token.create(
        db, user_id=user.id, token=refresh_token_str, expires_at=refresh_expiry
    )

    user_response = await _build_user_response(db, user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        token_type="bearer",
        user=user_response,
    )

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token using valid refresh token",
)
async def refresh_token(
    refresh_in: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        payload = decode_token(refresh_in.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id_str = payload.get("sub")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Check if refresh token exists in database and is not revoked
    db_token = await crud_token.get_valid_token(db, refresh_in.refresh_token)
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is revoked or expired",
        )

    # Revoke old refresh token (Token rotation for security)
    await crud_token.revoke(db, refresh_in.refresh_token)

    # Fetch user
    user = await crud_user.get_by_id(db, db_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found",
        )

    # Issue new access + refresh token
    user_roles_list = [r.code for r in user.roles]
    new_access_token = create_access_token(
        subject=str(user.id),
        extra_claims={"email": user.email, "roles": user_roles_list},
    )
    new_refresh_token_str = create_refresh_token(subject=str(user.id))

    new_refresh_expiry = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    await crud_token.create(
        db, user_id=user.id, token=new_refresh_token_str, expires_at=new_refresh_expiry
    )

    user_response = await _build_user_response(db, user)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token_str,
        token_type="bearer",
        user=user_response,
    )

@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout user and revoke refresh token",
)
async def logout(
    refresh_in: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    await crud_token.revoke(db, refresh_in.refresh_token)
    return MessageResponse(message="Successfully logged out and session revoked.")

@router.get(
    "/me",
    response_model=UserWithRolesResponse,
    summary="Get current logged in user profile with permissions",
)
async def get_me(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await _build_user_response(db, current_user)

@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change user password",
)
async def change_password(
    pwd_in: ChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not verify_password(pwd_in.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password does not match",
        )
    await crud_user.update_password(db, current_user, pwd_in.new_password)
    # Revoke all existing sessions for security
    await crud_token.revoke_all_for_user(db, current_user.id)
    return MessageResponse(message="Password successfully changed. Please log in again.")
