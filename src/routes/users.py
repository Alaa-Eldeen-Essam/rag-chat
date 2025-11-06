from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import JSONResponse
from routes.schemes.users import UserRegisterRequest, AdminCreateRequest
from controllers import UserController
from models.UserModel import UserModel
from models import ResponseSignal
from models.db_schemes import User
from routes.dependencies import get_current_user

users_router = APIRouter(
    prefix="/api/v1/users",
    tags=["api_v1", "users"],
)

@users_router.post("/register")
async def register_user(request: Request, register_request: UserRegisterRequest):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )
    user_controller = UserController()

    user, signal = await user_controller.register_user(
        user_model=user_model,
        username=register_request.username,
        password=register_request.password,
    )

    if not user:
        if signal == ResponseSignal.USER_ALREADY_EXISTS.value:
            status_code_response = status.HTTP_409_CONFLICT
        else:
            status_code_response = status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code_response,
            content={
                "signal": signal
            }
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": signal,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            }
        }
    )

@users_router.post("/admin")
async def create_admin_user(
    request: Request,
    admin_request: AdminCreateRequest,
    current_user: User = Depends(get_current_user),
):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )
    user_controller = UserController()

    user, signal = await user_controller.create_admin_user(
        user_model=user_model,
        requesting_user=current_user,
        username=admin_request.username,
        password=admin_request.password,
    )

    if not user:
        status_code_response = status.HTTP_403_FORBIDDEN if signal == ResponseSignal.ACCESS_FORBIDDEN_ERROR.value else status.HTTP_400_BAD_REQUEST
        if signal == ResponseSignal.USER_ALREADY_EXISTS.value:
            status_code_response = status.HTTP_409_CONFLICT
        return JSONResponse(
            status_code=status_code_response,
            content={
                "signal": signal
            }
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": signal,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_admin,
            }
        }
    )
