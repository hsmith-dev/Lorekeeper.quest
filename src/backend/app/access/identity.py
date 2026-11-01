"""Who is calling: the bearer-token user (moved from app/api/deps.py).

It lives in app.access so `require_campaign` can depend on the user without
app.access importing app.api (AD-1 layers). app.api.deps re-exports these
same objects, so `app.dependency_overrides[get_current_user]` keeps working
whichever module a test imports it from.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token_payload
from app.db.models.user import User
from app.db.session import get_db

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token_payload(credentials.credentials)
    user_id = payload["sub"]
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.password_changed_at is not None and payload.get("iat") is not None:
        token_issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        if token_issued_at < user.password_changed_at:
            # Token predates the account's last password reset — reject it
            # even though it's not expired yet. See User.password_changed_at.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session is no longer valid — please log in again.",
            )
    if user.is_suspended:
        # Checked here, not just in require_active_account, so a suspension
        # blocks *everything* — billing status, settings, avatar upload, not
        # just feature routes — and can't be bypassed by an already-active
        # subscription (access_granted is billing-derived and gets
        # recomputed by the Stripe webhook independent of this).
        detail = "Your account has been suspended."
        if user.suspended_reason:
            detail += f" Reason: {user.suspended_reason}"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return user
