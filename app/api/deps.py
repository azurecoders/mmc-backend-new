import uuid
from typing import Annotated, List, Set
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.crud.crud_user import crud_user
from app.models.user import User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str, Depends(reusable_oauth2)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        token_type = payload.get("type")
        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id_str: str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = await crud_user.get_by_id(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account",
        )
    return user

async def get_current_user_permissions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Set[str]:
    """Retrieves all effective permissions for current user."""
    return await crud_user.get_effective_permissions(db, current_user)

class PermissionChecker:
    """
    Dynamic Permission Checker Dependency.
    Bypasses if user has wildcard '*' permission or SUPER_ADMIN role.
    Otherwise checks if all/any required permissions are present.
    """
    def __init__(self, required_permissions: List[str], require_all: bool = True):
        self.required_permissions = set(required_permissions)
        self.require_all = require_all

    async def __call__(
        self,
        db: Annotated[AsyncSession, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_permissions = await crud_user.get_effective_permissions(db, current_user)

        # Super admin wildcard check
        if "*" in user_permissions:
            return current_user

        if self.require_all:
            missing_permissions = self.required_permissions - user_permissions
            if missing_permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Forbidden: Missing required permission(s): {', '.join(sorted(missing_permissions))}",
                )
        else:
            has_any = bool(self.required_permissions & user_permissions)
            if not has_any:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Forbidden: Requires at least one permission: {', '.join(sorted(self.required_permissions))}",
                )

        return current_user

def require_permissions(permissions: List[str], require_all: bool = True):
    return PermissionChecker(permissions, require_all=require_all)

class RoleChecker:
    """
    Dynamic Role Checker Dependency.
    Checks if user has any of the listed roles.
    """
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = {r.upper() for r in allowed_roles}

    async def __call__(
        self,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role_codes = {role.code for role in current_user.roles}
        if "SUPER_ADMIN" in user_role_codes:
            return current_user
        if not bool(self.allowed_roles & user_role_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: User does not have any of the allowed roles: {', '.join(sorted(self.allowed_roles))}",
            )
        return current_user

def require_roles(role_codes: List[str]):
    return RoleChecker(role_codes)
