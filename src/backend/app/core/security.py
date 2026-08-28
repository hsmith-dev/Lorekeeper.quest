from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from bcrypt import hashpw, checkpw, gensalt
from fastapi import HTTPException, status
from app.core.config import get_settings

settings = get_settings()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return hashpw(password.encode(), gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    # "iat" is what get_current_user compares against User.password_changed_at
    # to reject tokens issued before the account's last password reset — see
    # that field's docstring in app/db/models/user.py.
    return jwt.encode({"sub": user_id, "iat": now, "exp": expire}, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    return decode_token_payload(token)["sub"]


def decode_token_payload(token: str) -> dict:
    """Like decode_token, but returns the full claim set — callers that need
    "iat" (currently just get_current_user, for the password-reset session
    check) use this instead of the plain user-id-only decode_token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
