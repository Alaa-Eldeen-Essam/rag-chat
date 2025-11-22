from pydantic import BaseModel, constr
from typing import Optional


class AuthRequest(BaseModel):
    username: constr(min_length=3, max_length=128)
    password: constr(min_length=6, max_length=256)


class AuthUser(BaseModel):
    id: int
    username: str
    is_admin: bool
    department: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUser
