from fastapi import Depends, HTTPException, status, Request
from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from controllers import UserController
from models.UserModel import UserModel
from models import ResponseSignal
from helpers.jwt import decode_access_token


basic_security = HTTPBasic(auto_error=False)
bearer_security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials = Depends(bearer_security),
    credentials: HTTPBasicCredentials = Depends(basic_security),
):
    user_model = await UserModel.create_instance(
        db_client=request.app.db_client
    )

    # Bearer token flow
    if bearer and bearer.scheme.lower() == "bearer":
        payload = decode_access_token(bearer.credentials)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"signal": ResponseSignal.INVALID_CREDENTIALS_ERROR.value},
            )
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"signal": ResponseSignal.INVALID_CREDENTIALS_ERROR.value},
            )
        user = await user_model.get_user_by_id(int(user_id))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"signal": ResponseSignal.INVALID_CREDENTIALS_ERROR.value},
            )
        return user

    # Basic Auth fallback (legacy scripts / first-party login)
    if not credentials or not credentials.username or credentials.password is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"signal": ResponseSignal.INVALID_CREDENTIALS_ERROR.value},
            headers={"WWW-Authenticate": "Basic"},
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
                "signal": error_signal or ResponseSignal.INVALID_CREDENTIALS_ERROR.value
            },
            headers={"WWW-Authenticate": "Basic"},
        )

    await user_model.update_last_login(user_id=user.id)
    return user
