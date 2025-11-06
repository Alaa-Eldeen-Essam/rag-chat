import bcrypt
from typing import Optional

def hash_password(password: str) -> str:
    if password is None:
        raise ValueError("Password cannot be None")
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    if password is None or hashed_password is None:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False

def update_password_if_needed(password: Optional[str], hashed_password: Optional[str]) -> Optional[str]:
    if password is None:
        return hashed_password
    if hashed_password and verify_password(password, hashed_password):
        return hashed_password
    return hash_password(password)
