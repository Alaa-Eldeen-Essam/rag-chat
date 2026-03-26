from fastapi import APIRouter, Depends, HTTPException, Request, status

from controllers.UserController import UserController
from helpers.config import get_settings
from helpers.jwt import create_access_token
from models import ResponseSignal
from models.UserModel import UserModel
from routes.schemes.auth import AuthRequest, AuthResponse, AuthUser


settings = get_settings()

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@auth_router.post("/login", response_model=AuthResponse)
async def login(auth_request: AuthRequest, request: Request):
    user_model = await UserModel.create_instance(db_client=request.app.db_client)
    user_controller = UserController()
    user, error_signal = await user_controller.authenticate_user(
        user_model=user_model,
        username=auth_request.username,
        password=auth_request.password,
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"signal": error_signal or ResponseSignal.INVALID_CREDENTIALS_ERROR.value},
        )

    token = create_access_token(
        {
            "sub": user.username,
            "user_id": user.id,
            "is_admin": bool(user.is_admin),
        }
    )

    await user_model.update_last_login(user_id=user.id)

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=AuthUser(
            id=user.id,
            username=user.username,
            is_admin=bool(user.is_admin),
            department=getattr(user, "department", None),
        ),
    )
