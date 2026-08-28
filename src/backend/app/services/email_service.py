import logging
import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"

# Matches the plan/access_source vocabulary used throughout billing_service.py
# and the homepage pricing cards — kept in sync manually since there are only
# four values and they rarely change.
_TIER_LABELS = {
    "promo": "Free (Invite Only)",
    "byok": "Bring Your Own Key ($5/mo)",
    "hosted": "Hosted Model ($15/mo)",
    "grandfathered": "Full Access",
}


async def send_email(to: str, subject: str, html: str) -> bool:
    """Low-level send via Resend's HTTP API. Returns False (never raises) on
    any failure — missing config, network error, or Resend rejecting the
    request — so a broken email integration can't take down registration,
    login, or password reset. Callers that need to know delivery actually
    happened (there are none currently) can check the return value; the ones
    that exist today (welcome/reset emails) are all best-effort."""
    settings = get_settings()
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — skipping email to %s: %r", to, subject)
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _RESEND_API_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.resend_from_email, "to": [to], "subject": subject, "html": html},
            )
            r.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send email to %s: %r", to, subject)
        return False


def _wrap(preheader: str, body_html: str) -> str:
    """Shared chrome so every Lorekeeper email looks like it came from the
    same place — deliberately minimal (no external assets/fonts: some mail
    clients strip <link> tags or block remote resources by default, and
    inline styles are the one thing that reliably survives every client)."""
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f4f1ea;font-family:Georgia,'Times New Roman',serif;">
  <span style="display:none;font-size:1px;color:#f4f1ea;">{preheader}</span>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ea;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e0dccf;">
        <tr><td style="background:#3d2b1f;padding:20px 28px;">
          <span style="color:#e8c88a;font-size:22px;font-weight:bold;letter-spacing:0.03em;">Lorekeeper</span>
        </td></tr>
        <tr><td style="padding:28px;color:#2b2b2b;font-size:15px;line-height:1.6;">
          {body_html}
        </td></tr>
        <tr><td style="padding:16px 28px;background:#faf8f3;border-top:1px solid #e0dccf;">
          <span style="color:#8a8577;font-size:12px;">Lorekeeper &mdash; a chronicle for your table. Created by
            <a href="https://harrisonsmith.ai" style="color:#8a8577;">HarrisonSmith.AI</a></span>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def send_welcome_email(display_name: str, email: str, tier: str | None) -> bool:
    """Fired once per account, from two different call sites depending on how
    access was actually granted (see auth.py's register() for promo/gated
    signups, billing_service.py's checkout.session.completed handler for
    paid signups) — tier is only known for certain at whichever of those
    moments actually happens, not necessarily at registration itself."""
    tier_label = _TIER_LABELS.get(tier or "", None)
    tier_html = (
        f'<p style="margin:0 0 16px;">You\'re on the <strong>{tier_label}</strong> tier.</p>'
        if tier_label
        else (
            '<p style="margin:0 0 16px;">Your account is created, but not active yet &mdash; '
            'subscribe or redeem a promo code to start chronicling.</p>'
        )
    )
    body = f"""
      <h1 style="margin:0 0 16px;font-size:20px;color:#3d2b1f;">Welcome, {display_name}.</h1>
      <p style="margin:0 0 16px;">Your Lorekeeper account has been created.</p>
      {tier_html}
      <a href="https://lorekeeper.quest/dashboard" style="display:inline-block;background:#3d2b1f;color:#e8c88a;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Begin Your Journey</a>
    """
    return await send_email(email, "Welcome to Lorekeeper", _wrap("Your Lorekeeper account is ready.", body))


async def send_admin_message_email(display_name: str, email: str, subject: str, message: str) -> bool:
    """A message sent by the operator to a specific user (see
    app/api/routes/admin.py's POST /users/{id}/message) — account warnings,
    suspension notices, support replies, etc. message is plain text from the
    admin's textarea; escaped and line-break-converted here rather than
    trusting it as HTML, since it's operator input, not a template."""
    import html as _html

    safe_message = _html.escape(message).replace("\n", "<br>")
    body = f"""
      <h1 style="margin:0 0 16px;font-size:20px;color:#3d2b1f;">{_html.escape(subject)}</h1>
      <p style="margin:0 0 16px;">Hi {display_name},</p>
      <p style="margin:0 0 16px;">{safe_message}</p>
      <p style="margin:16px 0 0;color:#8a8577;font-size:13px;">— The Lorekeeper team</p>
    """
    return await send_email(email, subject, _wrap(subject, body))


async def send_password_reset_email(display_name: str, email: str, reset_link: str) -> bool:
    settings = get_settings()
    body = f"""
      <h1 style="margin:0 0 16px;font-size:20px;color:#3d2b1f;">Reset your password</h1>
      <p style="margin:0 0 16px;">Hi {display_name}, someone (hopefully you) requested a password reset for this account.</p>
      <a href="{reset_link}" style="display:inline-block;background:#3d2b1f;color:#e8c88a;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Reset Password</a>
      <p style="margin:16px 0 0;color:#8a8577;font-size:13px;">This link expires in {settings.password_reset_token_expire_minutes} minutes. If you didn't request this, you can safely ignore this email &mdash; your password won't change.</p>
    """
    return await send_email(email, "Reset your Lorekeeper password", _wrap("Reset your Lorekeeper password.", body))
