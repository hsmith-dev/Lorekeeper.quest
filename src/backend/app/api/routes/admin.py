import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.db.models.promo_code import PromoCode, PromoCodeRedemption
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.admin_message import AdminMessage
from app.schemas.admin import (
    AdminUserResponse,
    SuspendUserRequest,
    SetUserAccessRequest,
    AdminMessageRequest,
    PromoCodeAdminResponse,
    PromoCodeRedemptionResponse,
    PromoCodeCreateRequest,
    PromoCodeUpdateRequest,
    AppConfigResponse,
    AppConfigUpdateRequest,
    ManagedModelStatus,
    ModelLibraryResponse,
    ModelInstallRequest,
    LogsResponse,
)
from app.api.deps import require_admin
from app.services.email_service import send_admin_message_email
from app.services.billing_service import admin_cancel_subscription, admin_set_access

router = APIRouter()


# ── Users ────────────────────────────────────────────────────────────────────

async def _user_to_admin_response(db: AsyncSession, user: User) -> AdminUserResponse:
    """Single-user version of list_users' bulk query — used by every mutation
    route below so the response they return is exactly as fresh/accurate as
    the list view, not a hand-built partial response with placeholder
    subscription/count fields."""
    sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = sub_result.scalar_one_or_none()
    promo_result = await db.execute(
        select(PromoCode.code)
        .join(PromoCodeRedemption, PromoCodeRedemption.promo_code_id == PromoCode.id)
        .where(PromoCodeRedemption.user_id == user.id)
    )
    promo_code = promo_result.scalar_one_or_none()
    campaign_count = (
        await db.execute(select(func.count(Campaign.id)).where(Campaign.user_id == user.id))
    ).scalar() or 0
    journal_count = (
        await db.execute(select(func.count(JournalEntry.id)).where(JournalEntry.user_id == user.id))
    ).scalar() or 0
    return AdminUserResponse(
        id=user.id, email=user.email, display_name=user.display_name, created_at=user.created_at,
        access_granted=user.access_granted, access_source=user.access_source,
        is_suspended=user.is_suspended, suspended_reason=user.suspended_reason, is_admin=user.is_admin,
        subscription_plan=sub.plan if sub else None, subscription_status=sub.status if sub else None,
        tokens_used_current_period=sub.tokens_used_current_period if sub else None,
        tokens_included_per_period=sub.tokens_included_per_period if sub else None,
        promo_code_used=promo_code, campaign_count=campaign_count, journal_entry_count=journal_count,
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[AdminUserResponse]:
    users_result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = list(users_result.scalars().all())
    if not users:
        return []
    user_ids = [u.id for u in users]

    subs_result = await db.execute(select(Subscription).where(Subscription.user_id.in_(user_ids)))
    subs_by_user = {s.user_id: s for s in subs_result.scalars().all()}

    promo_result = await db.execute(
        select(PromoCodeRedemption.user_id, PromoCode.code)
        .join(PromoCode, PromoCodeRedemption.promo_code_id == PromoCode.id)
        .where(PromoCodeRedemption.user_id.in_(user_ids))
    )
    promo_by_user = {uid: code for uid, code in promo_result.all()}

    campaign_counts = dict(
        (
            await db.execute(
                select(Campaign.user_id, func.count(Campaign.id)).where(Campaign.user_id.in_(user_ids)).group_by(Campaign.user_id)
            )
        ).all()
    )
    journal_counts = dict(
        (
            await db.execute(
                select(JournalEntry.user_id, func.count(JournalEntry.id))
                .where(JournalEntry.user_id.in_(user_ids))
                .group_by(JournalEntry.user_id)
            )
        ).all()
    )

    out = []
    for u in users:
        sub = subs_by_user.get(u.id)
        out.append(
            AdminUserResponse(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                created_at=u.created_at,
                access_granted=u.access_granted,
                access_source=u.access_source,
                is_suspended=u.is_suspended,
                suspended_reason=u.suspended_reason,
                is_admin=u.is_admin,
                subscription_plan=sub.plan if sub else None,
                subscription_status=sub.status if sub else None,
                tokens_used_current_period=sub.tokens_used_current_period if sub else None,
                tokens_included_per_period=sub.tokens_included_per_period if sub else None,
                promo_code_used=promo_by_user.get(u.id),
                campaign_count=campaign_counts.get(u.id, 0),
                journal_entry_count=journal_counts.get(u.id, 0),
            )
        )
    return out


@router.post("/users/{user_id}/suspend", response_model=AdminUserResponse)
async def suspend_user(
    user_id: uuid.UUID, body: SuspendUserRequest, db: AsyncSession = Depends(get_db)
) -> AdminUserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_suspended = True
    user.suspended_reason = body.reason
    user.suspended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return await _user_to_admin_response(db, user)


@router.post("/users/{user_id}/unsuspend", response_model=AdminUserResponse)
async def unsuspend_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AdminUserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_suspended = False
    user.suspended_reason = None
    user.suspended_at = None
    await db.commit()
    await db.refresh(user)
    return await _user_to_admin_response(db, user)


@router.patch("/users/{user_id}/access", response_model=AdminUserResponse)
async def set_user_access(
    user_id: uuid.UUID, body: SetUserAccessRequest, db: AsyncSession = Depends(get_db)
) -> AdminUserResponse:
    """Direct override of a user's access/tier — bypasses promo codes and
    Stripe entirely (see billing_service.admin_set_access). Use this to grant
    someone hosted access, change their tier, or revoke access, independent
    of however they originally got it."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await admin_set_access(db, user, body.access_granted, body.plan)
    await db.commit()
    await db.refresh(user)
    return await _user_to_admin_response(db, user)


@router.post("/users/{user_id}/promote", response_model=AdminUserResponse)
async def promote_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AdminUserResponse:
    """Grant admin access to another account — the whole point of moving off
    the single ADMIN_EMAIL env var (see User.is_admin's docstring): adding an
    admin is now a button in this panel, not an env var change + redeploy."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = True
    await db.commit()
    await db.refresh(user)
    return await _user_to_admin_response(db, user)


@router.post("/users/{user_id}/demote", response_model=AdminUserResponse)
async def demote_user(
    user_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> AdminUserResponse:
    if user_id == admin.id:
        # Same reasoning as blocking self-delete below — an admin revoking
        # their own access mid-session is never actually intentional.
        raise HTTPException(status_code=400, detail="Cannot revoke your own admin access.")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = False
    await db.commit()
    await db.refresh(user)
    return await _user_to_admin_response(db, user)


@router.post("/users/{user_id}/message", status_code=202)
async def message_user(
    user_id: uuid.UUID, body: AdminMessageRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.add(AdminMessage(user_id=user.id, subject=body.subject, message=body.message))
    await db.commit()
    # Best-effort, same as every other email send in this app — a broken
    # email integration must not block the audit log from being written.
    await send_admin_message_email(user.display_name, user.email, body.subject, body.message)
    return {"detail": "Message sent."}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    if user_id == admin.id:
        # Deleting your own admin account mid-session would orphan the
        # request itself (the JWT would still validate but the user row
        # it points at is gone) — not a real use case, just a footgun.
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account.")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    await admin_cancel_subscription(sub_result.scalar_one_or_none())
    # Cascades to campaigns/journals/chat sessions/subscription/feedback/etc.
    # via each model's ondelete="CASCADE" — see their FK definitions.
    await db.delete(user)
    await db.commit()


# ── Promo codes ──────────────────────────────────────────────────────────────

async def _promo_to_admin_response(db: AsyncSession, promo: PromoCode) -> PromoCodeAdminResponse:
    result = await db.execute(
        select(PromoCodeRedemption, User.email, User.display_name)
        .join(User, PromoCodeRedemption.user_id == User.id)
        .where(PromoCodeRedemption.promo_code_id == promo.id)
        .order_by(PromoCodeRedemption.created_at.desc())
    )
    redemptions = [
        PromoCodeRedemptionResponse(
            user_id=r.user_id, user_email=email, user_display_name=display_name, redeemed_at=r.created_at
        )
        for r, email, display_name in result.all()
    ]
    return PromoCodeAdminResponse(
        id=promo.id, code=promo.code, active=promo.active, max_redemptions=promo.max_redemptions,
        redemption_count=promo.redemption_count, expires_at=promo.expires_at, note=promo.note,
        grants_plan=promo.grants_plan, created_at=promo.created_at, redemptions=redemptions,
    )


@router.get("/promo-codes", response_model=list[PromoCodeAdminResponse])
async def list_promo_codes(db: AsyncSession = Depends(get_db)) -> list[PromoCodeAdminResponse]:
    result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    return [await _promo_to_admin_response(db, p) for p in result.scalars().all()]


@router.post("/promo-codes", response_model=PromoCodeAdminResponse, status_code=201)
async def create_promo_code(body: PromoCodeCreateRequest, db: AsyncSession = Depends(get_db)) -> PromoCodeAdminResponse:
    code = body.code.strip().upper()
    existing = await db.execute(select(PromoCode).where(PromoCode.code == code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Promo code '{code}' already exists.")
    promo = PromoCode(
        code=code, max_redemptions=body.max_redemptions, expires_at=body.expires_at, note=body.note,
        grants_plan=body.grants_plan,
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return await _promo_to_admin_response(db, promo)


@router.patch("/promo-codes/{promo_id}", response_model=PromoCodeAdminResponse)
async def update_promo_code(
    promo_id: uuid.UUID, body: PromoCodeUpdateRequest, db: AsyncSession = Depends(get_db)
) -> PromoCodeAdminResponse:
    promo = await db.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(promo, field, value)
    await db.commit()
    await db.refresh(promo)
    return await _promo_to_admin_response(db, promo)


@router.delete("/promo-codes/{promo_id}", status_code=204)
async def delete_promo_code(promo_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    promo = await db.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")
    # Redemption rows cascade-delete too (ondelete="CASCADE" on
    # PromoCodeRedemption.promo_code_id) — deletes the audit trail of who
    # used it, not just the code. Deactivating (PATCH active=false) is
    # usually the better move if you want to stop new redemptions while
    # keeping the history; delete is for genuinely removing a mistaken code.
    await db.delete(promo)
    await db.commit()


# ── Platform config ──────────────────────────────────────────────────────────

def _config_response(open_access_mode: bool) -> AppConfigResponse:
    from app.core.config import get_settings
    s = get_settings()
    return AppConfigResponse(
        open_access_mode=open_access_mode,
        stripe_configured=bool(
            s.stripe_secret_key and s.stripe_webhook_secret
            and s.stripe_price_id_byok and s.stripe_price_id_hosted
        ),
    )


@router.get("/config", response_model=AppConfigResponse)
async def get_platform_config(db: AsyncSession = Depends(get_db)) -> AppConfigResponse:
    """Current platform settings for the admin portal's Platform tab."""
    from app.services.app_config_service import get_app_config
    cfg = await get_app_config(db)
    return _config_response(cfg.open_access_mode)


@router.put("/config", response_model=AppConfigResponse)
async def update_platform_config(body: AppConfigUpdateRequest, db: AsyncSession = Depends(get_db)) -> AppConfigResponse:
    """Flip open-access mode live — no redeploy. Turning it OFF re-arms the
    promo/subscription gates for accounts without access_granted; accounts
    that already earned access (promo, subscription, or registered while
    open) keep it."""
    from app.services.app_config_service import get_app_config
    cfg = await get_app_config(db)
    cfg.open_access_mode = body.open_access_mode
    await db.commit()
    return _config_response(cfg.open_access_mode)


# ── System: model library ────────────────────────────────────────────────────
# Self-host quality-of-life: the stack ships with an EMPTY Ollama — the 4.4GB
# fine-tune isn't in the git repo — and "docker exec ... ollama create" is
# exactly the step new self-hosters skip, then hit "AI model unavailable" on
# their first chat while Test Connection's green light (which only proves the
# server answers) gaslights them. These routes make model install a button.

@router.get("/models", response_model=ModelLibraryResponse)
async def model_library() -> ModelLibraryResponse:
    from app.core.config import get_settings
    from app.services import ollama_service

    s = get_settings()
    status = await ollama_service.ollama_status()
    return ModelLibraryResponse(
        ollama_url=s.kobold_url,
        ollama_reachable=status["reachable"],
        ollama_error=status["error"],
        installed_models=status["models"],
        finetuned=ManagedModelStatus(
            name=s.kobold_model,
            installed=ollama_service.model_installed(s.kobold_model, status["models"]),
            source=f"Hugging Face · {ollama_service.HF_FINETUNED_REF}",
        ),
        base=ManagedModelStatus(
            name=s.kobold_base_model,
            installed=ollama_service.model_installed(s.kobold_base_model, status["models"]),
            source=f"Ollama library · {ollama_service.BASE_LIBRARY_REF}",
        ),
    )


@router.post("/models/install")
async def install_model(body: ModelInstallRequest):
    """SSE stream of install progress — pull from the public registry, then
    register under the name the app expects. The X-Accel-Buffering header is
    what makes the progress bar live through nginx without a dedicated
    proxy_buffering-off location block."""
    import json as _json
    from fastapi.responses import StreamingResponse
    from app.services import ollama_service

    async def gen():
        async for event in ollama_service.install_model_events(body.variant):
            yield f"data: {_json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── System: logs & support bundle ────────────────────────────────────────────

def _read_log_tail(max_lines: int = 500, max_bytes: int = 2 * 1024 * 1024) -> tuple[str, list[str]]:
    """Last `max_lines` log lines: the shared LOG_FILE if configured and
    present (covers all workers), else this worker's in-memory ring buffer."""
    from pathlib import Path
    from app.core.config import get_settings
    from app.core.logging import RECENT_LOGS

    log_file = get_settings().log_file
    if log_file and Path(log_file).is_file():
        try:
            with open(log_file, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                text_tail = f.read().decode("utf-8", errors="replace")
            lines = text_tail.splitlines()
            if size > max_bytes and lines:
                lines = lines[1:]  # first line is almost certainly truncated
            return "file", lines[-max_lines:]
        except OSError:
            pass
    return "memory", list(RECENT_LOGS)[-max_lines:]


@router.get("/logs", response_model=LogsResponse)
async def recent_logs(lines: int = 200) -> LogsResponse:
    source, tail = _read_log_tail(max_lines=max(1, min(lines, 2000)))
    return LogsResponse(source=source, lines=tail)


@router.get("/support-bundle")
async def support_bundle(db: AsyncSession = Depends(get_db)):
    """One-click diagnostics zip a self-hoster can attach when asking for
    help: recent logs + a sanitized snapshot of environment/service state.
    Deliberately contains NO secrets — settings are reported as set/unset
    booleans or non-sensitive values only."""
    import io
    import json as _json
    import platform as _platform
    import sys as _sys
    import zipfile
    from datetime import datetime as _dt, timezone as _tz
    from fastapi.responses import StreamingResponse
    from sqlalchemy import text as _text
    from app.core.config import get_settings
    from app.services import ollama_service

    s = get_settings()

    db_ok, alembic_version = False, None
    try:
        db_ok = (await db.execute(_text("SELECT 1"))).scalar() == 1
        alembic_version = (await db.execute(_text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception:
        pass

    open_access = None
    try:
        from app.services.app_config_service import get_app_config
        open_access = (await get_app_config(db)).open_access_mode
    except Exception:
        pass

    ollama = await ollama_service.ollama_status()

    diagnostics = {
        "generated_at": _dt.now(_tz.utc).isoformat(),
        "app_version": "0.1.0",
        "python": _sys.version,
        "platform": _platform.platform(),
        "environment": s.environment,
        "log_level": s.log_level,
        "log_file_configured": bool(s.log_file),
        "open_access_mode": open_access,
        "database": {"reachable": db_ok, "alembic_version": alembic_version},
        "model_server": {
            "kobold_url": s.kobold_url,
            "expected_models": {"finetuned": s.kobold_model, "base": s.kobold_base_model},
            "ollama": ollama,
            "timeout_seconds": s.kobold_timeout_seconds,
        },
        "integrations": {
            "stripe_configured": bool(s.stripe_secret_key and s.stripe_webhook_secret),
            "email_configured": bool(s.resend_api_key),
            "admin_email_set": bool(s.admin_email),
        },
        "cors_origins": s.cors_origins,
    }

    source, log_lines = _read_log_tail(max_lines=2000)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diagnostics.json", _json.dumps(diagnostics, indent=2, default=str))
        zf.writestr(f"backend-logs-{source}.log", "\n".join(log_lines))
    buf.seek(0)

    stamp = _dt.now(_tz.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="lorekeeper-support-{stamp}.zip"'},
    )
