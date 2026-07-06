import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user import user_repository
from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token

logger = logging.getLogger("app.services.auth")

class AuthenticationService:
    """
    AuthenticationService orchestrates credentials check, password hashing, 
    and JWT tokens generation for users.
    """
    
    async def register_user(
        self, db: AsyncSession, *, email: str, name: Optional[str] = None, password: str
    ) -> User:
        """
        Registers a new user on the platform. 
        Ensures email uniqueness and hashes passwords securely.
        """
        # Check if email exists
        existing_user = await user_repository.get_user_by_email(db, email=email)
        if existing_user:
            logger.warning(f"Registration failed: Email '{email}' is already registered.")
            raise ValueError("Email already registered.")

        # Create hashed password credentials
        hashed_password = hash_password(password)
        
        user_in = {
            "email": email,
            "name": name,
            "password_hash": hashed_password,
            "is_active": True
        }
        
        logger.info(f"Registering new user: {email}")
        return await user_repository.create_user(db, obj_in=user_in)

    async def authenticate_user(
        self, db: AsyncSession, *, email: str, password: str
    ) -> Optional[User]:
        """
        Verifies login credentials.
        Returns the User instance if valid, otherwise None.
        """
        user = await user_repository.get_user_by_email(db, email=email)
        if not user:
            logger.warning(f"Authentication failed: User with email '{email}' not found.")
            return None
            
        if not verify_password(password, user.password_hash):
            logger.warning(f"Authentication failed: Incorrect password for user '{email}'.")
            return None
            
        if not user.is_active:
            logger.warning(f"Authentication failed: Account '{email}' is deactivated.")
            return None

        logger.info(f"User authenticated successfully: {email}")
        return user

    def issue_tokens(self, user: User) -> Dict[str, str]:
        """
        Generates access and refresh tokens for authenticated users.
        """
        # Subject contains the User ID
        subject = str(user.id)
        
        access_token = create_access_token(subject=subject)
        refresh_token = create_refresh_token(subject=subject)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

auth_service = AuthenticationService()
