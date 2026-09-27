"""API endpoints for authentication and user management."""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.database import get_db
from app.services import hub
from app.services.auth import AuthService
from app.models.user import User
from app.utils.auth import get_current_user

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["authentication"])
auth_service = AuthService()
security = HTTPBearer()


# Pydantic models for request/response
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_superuser: bool
    last_login: Optional[datetime]
    created_at: datetime


class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    is_superuser: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def require_password_login():
    """Password sign-in is break-glass only; people sign in through the GTM Hub."""
    if not settings.allow_password_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password sign-in is disabled; sign in through the GTM Hub"
        )


def login_payload(user: User) -> dict:
    """Access token response shared by password and hub sign-in."""
    access_token = auth_service.create_access_token(
        data={"sub": str(user.id), "username": user.username}
    )
    return LoginResponse(
        access_token=access_token,
        expires_in=auth_service.token_expire_minutes * 60,
        user={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_superuser": user.is_superuser
        }
    ).model_dump()


@router.get("/hub")
async def hub_sign_in(
    request: Request,
    next_path: str = Query("/", alias="next"),
    db: Session = Depends(get_db)
):
    """Exchange the browser's GTM Hub session for a CrawlDoctor access token."""
    no_store = {"Cache-Control": "no-store"}

    # Every *.agitracker.io site receives the hub cookie, so only CrawlDoctor's
    # own pages may swap it for a token.
    if request.headers.get("sec-fetch-site") in ("same-site", "cross-site"):
        return JSONResponse(status_code=403, content={"error": "cross_origin"}, headers=no_store)

    try:
        session = await hub.verify("; ".join(request.headers.getlist("cookie")))
    except hub.HubUnavailable:
        return JSONResponse(
            status_code=503,
            content={"error": "hub_unavailable", "detail": "Sign-in service unavailable, try again shortly"},
            headers=no_store
        )

    if session.status == 401:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthenticated", "login_url": hub.login_url(next_path)},
            headers=no_store
        )
    if session.status == 403:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "no_access_url": hub.no_access_url()},
            headers=no_store
        )

    user = await auth_service.sync_hub_user(db, session.user)
    if not user.is_active:
        logger.warning("Hub sign-in refused: local user is deactivated", user_id=user.id)
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "Account is deactivated", "no_access_url": hub.no_access_url()},
            headers=no_store
        )

    return JSONResponse(
        content={**login_payload(user), "signout_url": hub.signout_url()},
        headers=no_store
    )


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(require_password_login)])
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user and return access token (break-glass only)."""
    try:
        user = await auth_service.authenticate_user(
            db=db,
            username=request.username,
            password=request.password
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        return login_payload(user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Login failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user information."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        last_login=current_user.last_login,
        created_at=current_user.created_at
    )


@router.post("/users", response_model=UserResponse)
async def create_user(
    request: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new user (admin only)."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    
    try:
        user = await auth_service.create_user(
            db=db,
            username=request.username,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            is_superuser=request.is_superuser
        )
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            last_login=user.last_login,
            created_at=user.created_at
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error("User creation failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )


@router.put("/password", dependencies=[Depends(require_password_login)])
async def change_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Change user password (break-glass only)."""
    try:
        # Verify current password
        if not auth_service.verify_password(request.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Update password
        success = await auth_service.update_user_password(
            db=db,
            user_id=current_user.id,
            new_password=request.new_password
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password"
            )
        
        return {"message": "Password updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Password change failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )


@router.post("/api-key/regenerate")
async def regenerate_api_key(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Regenerate API key for current user."""
    try:
        new_api_key = await auth_service.regenerate_api_key(
            db=db,
            user_id=current_user.id
        )
        
        if not new_api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to regenerate API key"
            )
        
        return {
            "api_key": new_api_key,
            "created_at": datetime.now().isoformat(),
            "message": "API key regenerated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("API key regeneration failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate API key"
        )


@router.get("/api-key")
async def get_api_key_info(
    current_user: User = Depends(get_current_user)
):
    """Get API key information (without revealing the key)."""
    return {
        "has_api_key": bool(current_user.api_key),
        "created_at": current_user.api_key_created_at.isoformat() if current_user.api_key_created_at else None,
        "key_prefix": current_user.api_key[:8] + "..." if current_user.api_key else None
    }


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user)
):
    """Logout user (client should discard token)."""
    return {"message": "Logged out successfully"}


@router.get("/validate")
async def validate_token(
    current_user: User = Depends(get_current_user)
):
    """Validate current token and return user info."""
    return {
        "valid": True,
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "is_superuser": current_user.is_superuser
        }
    }
