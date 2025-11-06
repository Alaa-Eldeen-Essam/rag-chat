from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from controllers import UserController
from models.UserModel import UserModel
from models import ResponseSignal

security = HTTPBasic()

async def get_current_user(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )

    user_controller = UserController()
    user, error_signal = await user_controller.authenticate_user(
        user_model=user_model,
        username=credentials.username,
        password=credentials.password,
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "signal": ResponseSignal.INVALID_CREDENTIALS_ERROR.value
            },
            headers={"WWW-Authenticate": "Basic"},
        )

    await user_model.update_last_login(user_id=user.id)

    return user
