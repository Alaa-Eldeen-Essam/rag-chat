from pydantic import BaseModel, constr
from typing import Optional


class UserRegisterRequest(BaseModel):
    username: constr(min_length=3, max_length=128)
    password: constr(min_length=6, max_length=256)


class AdminCreateRequest(UserRegisterRequest):
    role: Optional[constr(min_length=4, max_length=5)] = "user"  # "user" or "admin"
    department: Optional[constr(min_length=1, max_length=128)] = None


class DepartmentUpdateRequest(BaseModel):
    department: constr(min_length=1, max_length=128)


class UserAdminUpdateRequest(BaseModel):
    is_admin: bool


class UserBasicUpdateRequest(BaseModel):
    username: Optional[constr(min_length=3, max_length=128)] = None
    reset_password: Optional[bool] = False
