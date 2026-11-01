from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import ALGORITHM

# Default key stays the client address: auth, share and sources routes (which
# are unauthenticated or must be throttled per origin) keep IP keying.
limiter = Limiter(key_func=get_remote_address)

_BEARER_PREFIX = "bearer "


def user_or_ip(request: Request) -> str:
    """Rate-limit bucket key for authenticated AI/streaming routes.

    Returns ``user:<sub>`` when the request carries a ``Bearer`` JWT whose
    signature and expiry check out, otherwise the remote address. This is a
    bucket key only, NOT authentication: ``get_current_user`` remains the
    access check. It never touches the database and never raises — any
    decode problem (bad signature, expired, malformed, no ``sub``, non-Bearer
    scheme) just falls back to the IP key. The token is never logged.

    Keying per user rather than per IP stops a GM and their Players behind one
    home router (one NAT address) from sharing a single AI bucket.
    """
    try:
        header = request.headers.get("authorization") or ""
        if header[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX:
            token = header[len(_BEARER_PREFIX):].strip()
            if token:
                payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
                sub = payload.get("sub")
                if isinstance(sub, str) and sub:
                    return f"user:{sub}"
    except Exception:  # JWTError and anything else: fall back to IP
        pass
    return get_remote_address(request)
