"""Authentication and authorization service."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.models.user import User

logger = structlog.get_logger()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Service for user authentication and authorization."""
    
    def __init__(self):
        self.secret_key = settings.secret_key
        self.algorithm = settings.algorithm
        self.token_expire_minutes = settings.access_token_expire_minutes
    
    def hash_password(self, password: str) -> str:
        """Hash a password for storage."""
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def create_access_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.token_expire_minutes)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError as e:
            logger.warning("Token verification failed", error=str(e))
            return None
    
    def generate_api_key(self) -> str:
        """Generate a secure API key."""
        return secrets.token_urlsafe(32)
    
    async def authenticate_user(
        self,
        db: Session,
        username: str,
        password: str
    ) -> Optional[User]:
        """Authenticate a user with username and password."""
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()
        
        if not user:
            logger.warning("Authentication failed: user not found", username=username)
            return None
        
        if not user.is_active:
            logger.warning("Authentication failed: user inactive", username=username)
            return None
        
        if not self.verify_password(password, user.hashed_password):
            logger.warning("Authentication failed: invalid password", username=username)
            return None
        
        # Update last login
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        
        logger.info("User authenticated successfully", username=username, user_id=user.id)
        return user
    
    async def authenticate_api_key(
        self,
        db: Session,
        api_key: str
    ) -> Optional[User]:
        """Authenticate using API key."""
        user = db.query(User).filter(
            User.api_key == api_key,
            User.is_active == True
        ).first()
        
        if user:
            logger.info("API key authentication successful", user_id=user.id)
        else:
            logger.warning("API key authentication failed", api_key=api_key[:8] + "...")
        
        return user
    
    async def create_user(
        self,
        db: Session,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        is_superuser: bool = False
    ) -> User:
        """Create a new user."""
        # Check if user already exists
        existing_user = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            raise ValueError("User with this username or email already exists")
        
        # Create user
        hashed_password = self.hash_password(password)
        api_key = self.generate_api_key()
        
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            is_superuser=is_superuser,
            api_key=api_key,
            api_key_created_at=datetime.now(timezone.utc)
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info("User created successfully", username=username, user_id=user.id)
        return user
    
    async def sync_hub_user(
        self,
        db: Session,
        hub_user: Dict[str, Any]
    ) -> User:
        """Find or create the local user for a GTM Hub identity and mirror its name and role."""
        email = hub_user["email"].strip().lower()
        name = (hub_user.get("name") or "").strip()[:100] or None
        is_admin = hub_user.get("role") == "admin"

        user = db.query(User).filter(func.lower(User.email) == email).first()
        if not user:
            # The password is random and never shown: hub users can't use password sign-in.
            user = User(
                username=self._hub_username(db, email),
                email=email,
                hashed_password=self.hash_password(secrets.token_urlsafe(32)),
                full_name=name,
                is_active=True,
                is_superuser=is_admin,
                api_key=self.generate_api_key(),
                api_key_created_at=datetime.now(timezone.utc)
            )
            db.add(user)
            try:
                db.commit()
                logger.info("Created user from GTM Hub sign-in", email=email, is_superuser=is_admin)
            except IntegrityError:
                # Another request created the same user concurrently.
                db.rollback()
                user = db.query(User).filter(func.lower(User.email) == email).first()
                if not user:
                    raise

        if not user.is_active:
            return user

        # The hub is the source of truth for the role: re-sync it on every sign-in.
        user.is_superuser = is_admin
        if name:
            user.full_name = name
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        return user

    def _hub_username(self, db: Session, email: str) -> str:
        """Username for a new hub user: the email, or its local part if the email is too long."""
        max_length = User.__table__.c.username.type.length
        username = email if len(email) <= max_length else email.split("@", 1)[0][:max_length]
        if db.query(User.id).filter(User.username == username).first():
            username = f"{username[:max_length - 9]}-{secrets.token_hex(4)}"
        return username

    async def update_user_password(
        self,
        db: Session,
        user_id: int,
        new_password: str
    ) -> bool:
        """Update user password."""
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return False
        
        user.hashed_password = self.hash_password(new_password)
        db.commit()
        
        logger.info("Password updated successfully", user_id=user_id)
        return True
    
    async def regenerate_api_key(
        self,
        db: Session,
        user_id: int
    ) -> Optional[str]:
        """Regenerate API key for a user."""
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return None
        
        new_api_key = self.generate_api_key()
        user.api_key = new_api_key
        user.api_key_created_at = datetime.now(timezone.utc)
        db.commit()
        
        logger.info("API key regenerated", user_id=user_id)
        return new_api_key
    
    async def deactivate_user(
        self,
        db: Session,
        user_id: int
    ) -> bool:
        """Deactivate a user account."""
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            return False
        
        user.is_active = False
        db.commit()
        
        logger.info("User deactivated", user_id=user_id)
        return True
    
    async def get_user_by_id(
        self,
        db: Session,
        user_id: int
    ) -> Optional[User]:
        """Get user by ID."""
        return db.query(User).filter(User.id == user_id).first()
    
    async def get_user_by_username(
        self,
        db: Session,
        username: str
    ) -> Optional[User]:
        """Get user by username."""
        return db.query(User).filter(User.username == username).first()
    
    def create_default_admin_sync(self, db: Session) -> User:
        """Create default admin user if it doesn't exist."""
        admin_user = db.query(User).filter(User.username == settings.admin_username).first()
        if admin_user:
            logger.info("Default admin user already exists")
            return admin_user
        
        try:
            # Create user directly without async call for simple creation
            hashed_password = self.hash_password(settings.admin_password)
            admin_user = User(
                username=settings.admin_username,
                email=settings.admin_email,
                hashed_password=hashed_password,
                full_name="Administrator",
                is_active=True,
                is_superuser=True
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
            logger.info("Default admin user created successfully")
            return admin_user
        except Exception as e:
            db.rollback()
            logger.error("Failed to create default admin user", error=str(e))
            raise
    
    def validate_token_payload(self, payload: Dict[str, Any]) -> Optional[int]:
        """Validate token payload and return user ID."""
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        try:
            return int(user_id)
        except (ValueError, TypeError):
            return None
    
    async def get_current_user(
        self,
        db: Session,
        token: str
    ) -> Optional[User]:
        """Get current user from JWT token."""
        payload = self.verify_token(token)
        if not payload:
            return None
        
        user_id = self.validate_token_payload(payload)
        if not user_id:
            return None
        
        return await self.get_user_by_id(db, user_id)
    
    def check_permission(
        self,
        user: User,
        permission: str,
        resource: Optional[str] = None
    ) -> bool:
        """Check if user has a specific permission."""
        # For now, simple role-based access
        # Superusers have all permissions
        if user.is_superuser:
            return True
        
        # Regular users have read-only access to their own data
        if permission in ["read", "view"]:
            return True
        
        # Write permissions require superuser
        if permission in ["write", "create", "update", "delete"]:
            return user.is_superuser
        
        return False
