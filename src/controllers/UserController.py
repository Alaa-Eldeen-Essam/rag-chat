from .BaseController import BaseController
from helpers.security import hash_password, verify_password
from models import ResponseSignal

class UserController(BaseController):

    def __init__(self):
        super().__init__()

    async def register_user(self, user_model, username: str, password: str):
        existing_user = await user_model.get_user_by_username(username=username)
        if existing_user:
            return None, ResponseSignal.USER_ALREADY_EXISTS.value

        password_hash = hash_password(password=password)
        user = await user_model.create_user(
            username=username,
            password_hash=password_hash,
            is_admin=False
        )
        return user, ResponseSignal.USER_CREATED_SUCCESS.value

    async def create_admin_user(self, user_model, requesting_user, username: str, password: str):
        if not requesting_user or not requesting_user.is_admin:
            return None, ResponseSignal.ACCESS_FORBIDDEN_ERROR.value

        existing_user = await user_model.get_user_by_username(username=username)
        if existing_user:
            return None, ResponseSignal.USER_ALREADY_EXISTS.value

        password_hash = hash_password(password=password)
        user = await user_model.create_user(
            username=username,
            password_hash=password_hash,
            is_admin=True
        )
        return user, ResponseSignal.ADMIN_CREATED_SUCCESS.value

    async def authenticate_user(self, user_model, username: str, password: str):
        user = await user_model.get_user_by_username(username=username)
        if not user:
            return None, ResponseSignal.INVALID_CREDENTIALS_ERROR.value

        if not verify_password(password=password, hashed_password=user.password_hash):
            return None, ResponseSignal.INVALID_CREDENTIALS_ERROR.value

        return user, None
