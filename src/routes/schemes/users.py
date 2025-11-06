from pydantic import BaseModel, constr

class UserRegisterRequest(BaseModel):
    username: constr(min_length=3, max_length=128)
    password: constr(min_length=6, max_length=256)

class AdminCreateRequest(UserRegisterRequest):
    pass
