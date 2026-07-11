from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, ExpiredSignatureError

from app.db.session import get_async_db
from app.schemas.user import UserCreate, UserResponse, UserLogin, TokenResponse, TokenRefreshRequest, TokenRefreshResponse, UserProfileUpdate, UserPasswordUpdate
from app.services.auth import auth_service
from app.core.responses import api_success_response, api_error_response
from app.dependencies import get_current_user
from app.models.user import User
from app.core.security import decode_token, verify_password, hash_password
from app.repositories.user import user_repository

router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Register a new platform user (Disabled - Registration is closed).
    """
    return api_error_response(
        message="Public registration is closed. Please ask your administrator to create an account.",
        code="REGISTRATION_CLOSED",
        status_code=status.HTTP_403_FORBIDDEN
    )

@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    credentials: UserLogin,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Authenticate a user and return access and refresh tokens.
    """
    try:
        user = await auth_service.authenticate_user(
            db,
            email=credentials.email,
            password=credentials.password
        )
        if not user:
            return api_error_response(
                message="Invalid email or password.",
                code="INVALID_CREDENTIALS",
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        
        # Issue JWT access and refresh tokens
        tokens = auth_service.issue_tokens(user)
        
        # Format the response
        response_data = TokenResponse(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_type=tokens["token_type"],
            user=UserResponse.model_validate(user)
        )
        
        return api_success_response(data=jsonable_encoder(response_data), status_code=status.HTTP_200_OK)
    except Exception as e:
        return api_error_response(
            message="An error occurred during authentication.",
            code="AUTHENTICATION_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve details of the currently authenticated user.
    """
    try:
        user_data = jsonable_encoder(UserResponse.model_validate(current_user))
        return api_success_response(data=user_data, status_code=status.HTTP_200_OK)
    except Exception as e:
        return api_error_response(
            message="Failed to retrieve current user profile.",
            code="GET_PROFILE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.put("/profile", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def update_profile(
    profile_in: UserProfileUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update currently authenticated user's profile details.
    """
    try:
        # Check if email is being changed
        if profile_in.email != current_user.email:
            return api_error_response(
                message="Email address cannot be changed.",
                code="EMAIL_CHANGE_PREVENTED",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        current_user.name = profile_in.name
        current_user.email = profile_in.email
        await db.commit()
        await db.refresh(current_user)
        
        user_data = jsonable_encoder(UserResponse.model_validate(current_user))
        return api_success_response(data=user_data, status_code=status.HTTP_200_OK)
    except Exception as e:
        return api_error_response(
            message="Failed to update profile.",
            code="PROFILE_UPDATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.put("/password", status_code=status.HTTP_200_OK)
async def update_password(
    password_in: UserPasswordUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update currently authenticated user's password.
    """
    try:
        # Verify current password
        if not verify_password(password_in.current_password, current_user.password_hash):
            return api_error_response(
                message="Incorrect current password.",
                code="INCORRECT_CURRENT_PASSWORD",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            
        current_user.password_hash = hash_password(password_in.new_password)
        await db.commit()
        
        return api_success_response(
            data={"message": "Password updated successfully."}
        )
    except Exception as e:
        return api_error_response(
            message="Failed to update password.",
            code="PASSWORD_UPDATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.post("/refresh", response_model=TokenRefreshResponse, status_code=status.HTTP_200_OK)
async def refresh_token(
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Validate refresh token and issue a new access/refresh token pair.
    """
    try:
        # Decode token
        token_data = decode_token(payload.refresh_token)
        
        # Check token type is refresh
        if token_data.get("type") != "refresh":
            return api_error_response(
                message="Invalid token type.",
                code="INVALID_TOKEN_TYPE",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            
        user_id = token_data.get("sub")
        if not user_id:
            return api_error_response(
                message="Could not validate credentials.",
                code="INVALID_CREDENTIALS",
                status_code=status.HTTP_401_UNAUTHORIZED
            )
            
        user = await user_repository.get_user_by_id(db, id=user_id)
        if not user:
            return api_error_response(
                message="User not found.",
                code="USER_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        if not user.is_active:
            return api_error_response(
                message="Inactive user account.",
                code="INACTIVE_USER",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            
        # Issue new tokens
        tokens = auth_service.issue_tokens(user)
        
        response_data = TokenRefreshResponse(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_type=tokens["token_type"]
        )
        
        return api_success_response(data=jsonable_encoder(response_data), status_code=status.HTTP_200_OK)
    except ExpiredSignatureError:
        return api_error_response(
            message="Refresh token has expired.",
            code="TOKEN_EXPIRED",
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    except JWTError:
        return api_error_response(
            message="Invalid refresh token.",
            code="INVALID_TOKEN",
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred during token refresh.",
            code="REFRESH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
