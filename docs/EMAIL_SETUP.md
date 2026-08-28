# Email Setup — Resend

Lorekeeper sends three kinds of email — a welcome email on account creation
(promo/gated signup) or on completing checkout (paid signup, once the tier is
actually known), and a password reset link. This doc is the steps *you* run
to make it live — the code side is already done
(`app/services/email_service.py`, wired into `app/api/routes/auth.py` and
`app/services/billing_service.py`'s webhook handler).

## Why Resend

Running your own SMTP server has poor deliverability by default — cloud
provider IP ranges (including OCI's) are commonly on spam blocklists, and
getting off one is a slow, manual process per-provider. A transactional email
API sidesteps that entirely: Resend's IPs have an established sending
reputation, and Lorekeeper's backend just POSTs to their HTTP API (via
`httpx`, already a dependency — no new SMTP-handling code or heavy SDK).

## 1. Create a Resend account and verify your domain

1. [resend.com/signup](https://resend.com/signup) — free, no card required
   for the free tier (3,000 emails/month).
2. Dashboard → **Domains** → **Add Domain** → enter `lorekeeper.quest` (or
   whichever domain you're sending from).
3. Resend shows you a handful of DNS records to add (typically an SPF-related
   `TXT`/`MX` pair and a DKIM `TXT` record under a
   `resend._domainkey.lorekeeper.quest`-style name — the exact values are
   generated per-account, copy them from Resend's dashboard, don't guess).
   Add each one at your DNS provider (Namecheap → Domain List →
   `lorekeeper.quest` → Manage → Advanced DNS — same place the `A` records
   for the OCI instance were added).
4. Back in Resend, click **Verify DNS Records**. Propagation is usually fast
   (minutes) but can take longer depending on your DNS provider/TTLs — the
   dashboard just shows "Pending" until it resolves, no need to keep
   re-clicking.
5. **Optional but recommended**: add a DMARC record too (Resend's docs cover
   this) — not required for sending to work, but improves deliverability and
   protects the domain from being spoofed by spammers.

## 2. Get an API key

Dashboard → **API Keys** → **Create API Key**. Full access is fine here —
unlike Stripe, Resend's API keys don't have the same granular
read/write/resource permission model to scope down; the blast radius of a
leaked key is "someone can send email as your verified domain," not access to
billing or account data.

## 3. Set the environment variables

In `.env` (see `.env.example`):

```
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Lorekeeper <noreply@lorekeeper.quest>
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=60
```

`RESEND_FROM_EMAIL` must be an address on the domain you just verified — a
send attempt from an unverified domain is rejected by Resend before it ever
reaches an inbox, and `email_service.py` logs (but doesn't raise on) any send
failure, so a mismatch here fails silently from the app's perspective. Check
Resend's dashboard → **Logs** if welcome/reset emails don't seem to be
arriving.

Restart the backend (`docker compose -f docker-compose.prod.yml restart backend`
or re-run `scripts/deploy-oci.sh`) to pick up the new values.

## 4. Test it

1. Register a new account (with or without a promo code) — confirm a welcome
   email arrives, and that it names the right tier (gated accounts get a
   "not active yet" message instead, since there's no tier until they
   subscribe or redeem a code).
2. Complete a checkout with a subscription — confirm a *second* welcome
   email arrives once the webhook processes, this time naming the actual
   paid tier ($5 BYOK or $15 Hosted).
3. On the login page, click **Forgot password?** → enter a registered
   email → confirm a reset email arrives with a working link → follow it,
   set a new password, confirm you can log in with it.
4. Try requesting a reset for an email that *isn't* registered — confirm the
   response is identical either way (no "email not found" — see
   `forgot_password`'s docstring in `auth.py` for why: a different response
   would let someone enumerate registered emails).

## What's NOT built

- **Email verification on signup** — registration doesn't require confirming
  the email address before the account works. Adding this is a mechanical
  extension of the same pattern (a token table + a `/verify-email` route),
  not a redesign, if it's ever needed.
- **Unsubscribe/preference management** — these are all transactional
  emails (account lifecycle events, not marketing), which don't legally
  require an unsubscribe link the way marketing email does. If a
  newsletter/announcement feature is ever added, that would need one.
