import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from PIL import Image
import io

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.promo_code import PromoCode, PromoCodeRedemption
from app.db.models.password_reset_token import PasswordResetToken
from app.schemas.auth import (
    UserCreate, UserLogin, TokenResponse, MeResponse, ForgotPasswordRequest, ResetPasswordRequest,
)
from app.core.security import hash_password, verify_password, create_access_token
from app.core.config import get_settings
from app.core.limiter import limiter
from app.api.deps import get_current_user
from app.services.email_service import send_welcome_email, send_password_reset_email

router = APIRouter()
logger = logging.getLogger(__name__)

_AVATAR_SIZE = 128  # px — thumbnail stored as base64

# Per-account lockout thresholds (see User.failed_login_attempts/locked_until
# docstrings) — deliberately generous: this exists to blunt distributed
# credential-stuffing, not to lock out someone who fat-fingered their
# password a couple of times. Self-clears after LOCKOUT_MINUTES; no admin
# action needed.
_MAX_FAILED_LOGIN_ATTEMPTS = 10
_LOCKOUT_MINUTES = 15

# A fixed, precomputed bcrypt hash checked against when the email in a login
# attempt doesn't exist at all — without this, verify_password is simply
# skipped for unknown emails, and that branch is measurably faster than the
# "wrong password for a real account" branch. That timing gap is a classic
# side channel for enumerating which emails have accounts; comparing against
# a dummy hash keeps both branches doing the same bcrypt work.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, body: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # A promo code, if given, is validated BEFORE the account is created — an
    # invalid code should fail loudly rather than silently create a gated
    # account the caller didn't ask for.
    promo: PromoCode | None = None
    if body.promo_code:
        promo_result = await db.execute(select(PromoCode).where(PromoCode.code == body.promo_code.strip()))
        promo = promo_result.scalar_one_or_none()
        if promo is None or not promo.is_redeemable():
            raise HTTPException(status_code=400, detail="That promo code isn't valid or has expired.")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
    )
    # First-run bootstrap: the very first account on a fresh deployment
    # becomes the admin — same pattern as Grafana/Portainer — so a
    # self-hoster never needs the ADMIN_EMAIL env var to reach the admin
    # portal (where the model install lives). Deliberately keyed on "no
    # users exist at all", NOT "no admin exists": on an established open
    # instance that somehow lost its admins, silently crowning the next
    # random registrant would be privilege escalation, not convenience.
    # ADMIN_EMAIL (see deps.is_admin_user) still works as an override.
    any_user = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
    if any_user is None:
        user.is_admin = True
        user.access_granted = True
        user.access_source = user.access_source or "grandfathered"
    if promo is not None:
        user.access_granted = True
        user.access_source = "promo"
    else:
        from app.services.app_config_service import is_open_access
        if await is_open_access(db):
            # Open-access mode (admin-portal checkbox): no promo or
            # subscription needed — everyone gets in. Covers self-hosters,
            # companies provisioning accounts for their users, and free
            # community servers alike.
            user.access_granted = True
            user.access_source = "open"
    # else: account is created but gated — access_granted defaults to False.
    # The frontend sends them to /subscribe, which calls POST /api/billing/checkout.

    db.add(user)
    await db.flush()  # assigns user.id without committing yet

    if promo is not None:
        db.add(PromoCodeRedemption(promo_code_id=promo.id, user_id=user.id))
        promo.redemption_count += 1
        from app.services.billing_service import apply_promo_plan
        await apply_promo_plan(db, user, promo)

    await db.commit()
    await db.refresh(user)
    token = create_access_token(str(user.id))
    # Best-effort — send_email never raises (see email_service.py), so a
    # broken/unconfigured email integration can't fail registration itself.
    await send_welcome_email(user.display_name, user.email, user.access_source)
    return TokenResponse(
        access_token=token, user_id=user.id, display_name=user.display_name, access_granted=user.access_granted
    )


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user)) -> MeResponse:
    from app.api.deps import is_admin_user

    is_admin = is_admin_user(user)
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_data=user.avatar_data,
        access_granted=user.access_granted,
        access_source=user.access_source,
        is_admin=is_admin,
        has_completed_tutorial=user.has_completed_tutorial,
    )


@router.post("/tutorial-complete", response_model=MeResponse)
async def complete_tutorial(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MeResponse:
    """Called once the onboarding tour finishes OR is explicitly skipped —
    either way it shouldn't auto-launch again on next login. The Settings
    page's "Replay Tutorial" button re-runs the tour client-side without
    calling this (it doesn't need to — the flag is already True by then)."""
    from app.api.deps import is_admin_user

    user.has_completed_tutorial = True
    await db.commit()
    await db.refresh(user)
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_data=user.avatar_data,
        access_granted=user.access_granted,
        access_source=user.access_source,
        is_admin=is_admin_user(user),
        has_completed_tutorial=user.has_completed_tutorial,
    )


@router.put("/me/avatar", response_model=MeResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Avatar image must be under 5 MB.")
    try:
        img = Image.open(io.BytesIO(contents)).convert("RGBA")
        img.thumbnail((_AVATAR_SIZE, _AVATAR_SIZE), Image.LANCZOS)
        # Composite onto white to handle transparency
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        buf = io.BytesIO()
        bg.save(buf, format="JPEG", quality=85)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        raise HTTPException(status_code=422, detail="Could not process image. Upload a JPEG or PNG.")
    user.avatar_data = data_url
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    ip = _client_ip(request)
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        # Rejected before even checking the password — an attacker who's
        # already tripped the lockout shouldn't get to keep guessing during
        # the cooldown, and there's no point paying the bcrypt cost either.
        logger.warning("Login blocked (account locked) for %s from %s", body.email, ip)
        raise HTTPException(
            status_code=403,
            detail="Too many failed login attempts. Try again in a few minutes.",
        )

    # Always do the bcrypt comparison, real user or not — see _DUMMY_HASH.
    password_ok = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)

    if not user or not password_ok:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= _MAX_FAILED_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=_LOCKOUT_MINUTES)
                logger.warning("Account locked after repeated failed logins: %s from %s", body.email, ip)
            await db.commit()
        logger.warning("Failed login attempt for %s from %s", body.email, ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.is_suspended:
        # Same check as get_current_user, done here too so a suspended user
        # gets a clear message immediately at login rather than a token that
        # then 403s on every subsequent request.
        detail = "Your account has been suspended."
        if user.suspended_reason:
            detail += f" Reason: {user.suspended_reason}"
        raise HTTPException(status_code=403, detail=detail)

    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.commit()

    token = create_access_token(str(user.id))
    return TokenResponse(
        access_token=token, user_id=user.id, display_name=user.display_name, access_granted=user.access_granted
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot-password", status_code=202)
@limiter.limit("5/hour")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Always returns the same generic response whether or not the email is
    registered — the response itself must not leak which emails have
    accounts (a distinguishable response here is a classic account
    enumeration vector). Rate-limited per IP on top of that, since even a
    constant-response endpoint can still be used to spam an inbox with reset
    emails if left unlimited."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is not None:
        # One outstanding token per user — old ones are simply superseded,
        # not tracked as "invalid" (no revocation list needed since they're
        # deleted outright).
        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        raw_token = secrets.token_urlsafe(32)
        settings = get_settings()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_expire_minutes)
        db.add(PasswordResetToken(user_id=user.id, token_hash=_hash_token(raw_token), expires_at=expires_at))
        await db.commit()
        reset_link = f"{settings.frontend_url}/reset-password?token={raw_token}"
        await send_password_reset_email(user.display_name, user.email, reset_link)
    return {"detail": "If that email has an account, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
@limiter.limit("10/hour")
async def reset_password(
    request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    token_hash = _hash_token(body.token)
    result = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    reset_token = result.scalar_one_or_none()
    if reset_token is None or reset_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    user = await db.get(User, reset_token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    user.hashed_password = hash_password(body.new_password)
    # Bumps the watermark get_current_user checks a token's "iat" against —
    # any session started before this reset stops working immediately,
    # rather than staying valid until its natural 24h expiry. See
    # User.password_changed_at.
    user.password_changed_at = datetime.now(timezone.utc)
    # A reset is also as good a signal as any that whatever locked the
    # account out (if it was) is resolved now that the real owner has proven
    # they control the email inbox.
    user.failed_login_attempts = 0
    user.locked_until = None
    # Delete every outstanding token for this user, not just the one used —
    # closes off any other reset link that might still be sitting in an
    # inbox (e.g. an earlier forgot-password request the user re-sent).
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    await db.commit()
    return {"detail": "Password has been reset. You can now sign in."}
