# Payment Processor Setup — Stripe

Lorekeeper's subscription/billing system (account gating, the hosted-model
quota, the public pricing page, the Settings → Billing panel) is built
against **Stripe**. This doc is the steps *you* run in the Stripe Dashboard
to make it live — the code side is already done
(`app/services/billing_service.py`, `app/api/routes/billing.py`).

## Two tiers

| | Bring Your Own Key | Hosted Model |
| --- | --- | --- |
| Price | **$5/mo** | **$15/mo** |
| App access (journals, campaigns, chat, sharing, etc.) | Full | Full |
| LLM | Your own OpenAI/Anthropic/Gemini/custom key | Lorekeeper's hosted model, metered, no key needed |
| Plan code | `"byok"` | `"hosted"` |

A free path also exists outside Stripe entirely: an operator-issued promo
code (`scripts/create_promo_code.py`) grants the same access as the BYOK
tier for free — no Stripe involvement at all. Both paid tiers and the promo
path grant identical *app* access; the only thing that differs is which LLM
a subscriber can use without supplying their own key
(`app/api/deps.py::get_user_llm_config`).

## Why Stripe

Handling card data directly means PCI compliance scope; Stripe Checkout and
the Customer Portal are both fully hosted, so Lorekeeper's backend never
touches a card number — it only ever sees a `customer_id`/`subscription_id`
and webhook events. For two recurring subscription tiers with a usage-quota
reset each period on one of them, Stripe's Checkout (mode=subscription) +
Billing Portal + webhooks cover the whole lifecycle with no custom UI needed
on our side. This is the standard choice for exactly this shape of product;
switching processors later is possible but not a small change (different
Checkout API, different webhook event vocabulary), so this doc assumes
Stripe throughout.

## 1. Create a Stripe account

[dashboard.stripe.com/register](https://dashboard.stripe.com/register). Free
to create; you only need real bank details when you're ready to accept live
payments. Everything below can (and should) be done in **test mode** first —
Stripe gives you a fully separate sandbox with fake card numbers
(`4242 4242 4242 4242`, any future expiry, any CVC) so you can run the entire
flow end-to-end without moving real money.

## 2. Create two products, each with its own price

**One Product per tier, never two prices for different tiers on one
Product** — Checkout and invoices show the Product name on each line item,
so two tiers sharing a Product would look identical to a customer. This is
already done in your connected sandbox (created via the Stripe MCP while
setting this up, so there's something to test against immediately):

| Tier | Product | Price |
| --- | --- | --- |
| Bring Your Own Key | "Lorekeeper — Bring Your Own Key" — `prod_XXXXXXXXXXXXXX` | $5.00/mo — `price_XXXXXXXXXXXXXXXXXXXXXXXX` |
| Hosted Model | "Lorekeeper — Hosted Model" — `prod_XXXXXXXXXXXXXX` | $15.00/mo — `price_XXXXXXXXXXXXXXXXXXXXXXXX` |

(An earlier single-tier "Lorekeeper Subscription" product/price from before
this two-tier split was archived, not deleted — Stripe objects can't be
hard-deleted once a Price has been used, only marked inactive. It won't show
up anywhere customer-facing.)

Both price IDs are already in `.env` locally for testing. **$5/$15 are
placeholders** — change either amount in Dashboard → **Product catalog**, or
create a new Price on the same Product and update the corresponding env var.
For a from-scratch setup (a different account, or once you're ready for live
mode), repeat this from Dashboard → **Product catalog** → **Add product**,
twice, once per tier:

- Name: e.g. "Lorekeeper — Bring Your Own Key" / "Lorekeeper — Hosted Model"
- Pricing model: **Recurring**, Monthly (matches
  `subscriptions.tokens_used_current_period` resetting on
  `invoice.payment_succeeded`, i.e. once per billing period — a different
  period still resets the quota correctly, just on that cadence instead)

Save each, open the price you just created, and copy its **Price ID**
(`price_xxxxxxxxxxxx` — not the Product ID, which starts with `prod_`).

## 3. Get your API key — use a Restricted API Key, not the full Secret Key

Dashboard → **Developers** → **API keys** → **Create restricted key**, not
the default "Secret key". A restricted key (`rk_test_...` / `rk_live_...`)
can only do what you explicitly grant it — if it ever leaks, the blast radius
is bounded to those permissions instead of full account access. Grant
exactly what `billing_service.py` actually calls, nothing more:

| Resource | Permission |
| --- | --- |
| Customers | Write |
| Checkout Sessions | Write |
| Customer Portal | Write |
| Products, Prices | (none needed — the backend only references the Price IDs you set in `.env`, never creates/lists products at runtime) |

This is what goes in `STRIPE_SECRET_KEY` despite the env var's name — any
`sk_`/`rk_`-prefixed secret works the same way to the SDK, and the restricted
key is the safer default. (There's also a publishable key, `pk_test_...`;
Lorekeeper doesn't need it since Checkout and the Portal are both
server-initiated redirects, not client-side Stripe.js.)

## 4. Set up the webhook

This is how Stripe tells the backend "payment succeeded" / "subscription
canceled" / etc. — `app/services/billing_service.py::handle_webhook_event`
is what processes these.

Dashboard → **Developers** → **Webhooks** → **Add endpoint**.

- Endpoint URL: `https://<your-domain>/api/billing/webhook`
  (local/dev: use the [Stripe CLI](https://stripe.com/docs/stripe-cli)
  instead — `stripe listen --forward-to localhost:8000/api/billing/webhook`
  gives you a `whsec_...` for local testing without a public URL)
- Events to send — select these six (`billing_service.py` only handles these,
  selecting more is harmless but unnecessary):
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_succeeded`
  - `invoice.payment_failed`

After creating the endpoint, open it and copy the **Signing secret**
(`whsec_...`) — this is `STRIPE_WEBHOOK_SECRET`, used to verify incoming
webhook requests are actually from Stripe (`stripe.Webhook.construct_event`
in `billing_service.py`) rather than someone POSTing fake "payment succeeded"
events at your server. This is the primary control and is mandatory — it's
already implemented and always checked before any event is processed.

**Optional defense-in-depth:** [allowlist Stripe's webhook IP ranges](https://docs.stripe.com/ips) at
the nginx/firewall level for the `/api/billing/webhook` path specifically, so
requests to that one path are rejected before they even reach signature
verification if they're not from Stripe's infrastructure. Not required —
signature verification alone is a strong guarantee — but cheap extra
insurance since Stripe publishes a stable IP list.

**Idempotency:** every event type this handler processes sets fields to an
absolute value taken from the event payload (subscription status, plan,
token count reset to `0`, etc.) rather than incrementing anything, so a
duplicate delivery of the same event (Stripe retries on timeout, and you can
also manually redeliver from the Dashboard) is naturally safe to process
twice — no separate "have I seen this event ID before" table needed for the
events currently handled.

**How plan (byok vs. hosted) is determined:** `checkout.session.completed`
reads it from the Checkout Session's `metadata.plan` (set when the session
was created, from whichever "Subscribe" button the user clicked). Every
`customer.subscription.*` event afterward re-derives it from the
subscription's *actual* Stripe price ID
(`_plan_from_subscription_obj` in `billing_service.py`) — that's the source
of truth, not what checkout merely started with, so it stays correct even if
a customer changes plans later through the Customer Portal.

## 5. Set the environment variables

In `.env` (see `.env.example`):

```
FRONTEND_URL=https://your-actual-domain.com
STRIPE_SECRET_KEY=rk_test_...          # the restricted key from step 3; rk_live_... once you go live
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_BYOK=price_...         # $5/mo tier
STRIPE_PRICE_ID_HOSTED=price_...       # $15/mo tier
SUBSCRIPTION_MONTHLY_TOKEN_QUOTA=1000000   # hosted-tier quota; not used by the byok tier
```

`FRONTEND_URL` matters here specifically because Checkout/Portal redirect
back to it (`success_url`/`cancel_url`/`return_url` in
`billing_service.py`) — get it wrong and users land on a broken URL after
paying, even though the payment itself went through fine.

Restart the backend (`docker compose -f docker-compose.prod.yml restart backend`
or re-run `scripts/deploy-oci.sh`) to pick up the new `.env` values.

## 6. Configure the Customer Portal to allow switching between the two tiers

By default the Customer Portal only lets a customer cancel or update their
payment method — **switching from one Product to the other isn't enabled
until you turn it on**:

Dashboard → **Settings** → **Billing** → **Customer portal** →
**Subscriptions** → enable "Customers can switch plans", and add both
Products (Bring Your Own Key, Hosted Model) to the list of plans they can
switch between. Without this, a subscriber on one tier who wants the other
has no self-serve path — `create_checkout_session` deliberately refuses to
start a second Checkout Session for someone with an active subscription
already (that would create a *second* Stripe subscription rather than
changing the existing one), and points them at the Portal instead.

## 7. Test the whole flow before going live

1. Register an account *without* a promo code — confirm it lands on
   `/subscribe` (this is `access_granted=False`).
2. On `/subscribe`, click **Subscribe** under **Bring Your Own Key** →
   Stripe's hosted Checkout for the $5 price.
3. Pay with the test card `4242 4242 4242 4242`, any future expiry/CVC/ZIP.
4. You should be redirected back with full access — check Settings →
   Billing shows "Bring Your Own Key ($5/mo)" and **no** usage bar (that
   tier never gets hosted-model access, so there's nothing to meter).
5. Confirm the gate actually works: try generating a journal entry with no
   personal LLM key configured — expect a 402 telling you to add a key or
   upgrade, **not** silent access to the hosted model.
6. In the Stripe Dashboard, find that test subscription and cancel it —
   confirm the next webhook delivery flips your account back to gated.
7. Repeat steps 1–4 with a fresh account on the **Hosted Model** ($15) plan
   instead — confirm Settings → Billing now shows a usage bar, and that
   generating content with no personal key configured actually reaches the
   hosted model (or fails with a *provider* error, e.g. Ollama unreachable —
   not a 402/403 access error).
8. From the $15 account, open **Manage Subscription** and confirm the two
   plans are listed as switchable (step 6 above) — try switching to the $5
   plan and confirm Settings → Billing updates accordingly after the
   webhook lands.
9. Check **Developers → Webhooks → [your endpoint] → recent deliveries** for
   any failures — a `400` there almost always means `STRIPE_WEBHOOK_SECRET`
   doesn't match what you set in `.env`.

## 8. Go live

Toggle out of test mode in the Stripe Dashboard (top-left), repeat steps 2–4
to create **live-mode** products/prices, a restricted key, and a webhook
endpoint (test and live mode are entirely separate — live-mode versions of
all of these are required even if you already made test-mode ones), redo
the Customer Portal configuration in step 6 (Portal settings are also
per-mode), and swap `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` /
`STRIPE_PRICE_ID_BYOK` / `STRIPE_PRICE_ID_HOSTED` in `.env` for the
live-mode values. Stripe requires your account to have real bank/tax details
on file before it lets you accept live payments — the Dashboard walks you
through that when you try to toggle live mode on.

**Sales tax / VAT / GST:** not configured. `billing_service.py` doesn't set
`automatic_tax` on the Checkout Session, so no tax is calculated or
collected right now — this is deliberate, not an oversight: turning
`automatic_tax` on without an active [Stripe Tax registration](https://docs.stripe.com/tax/registering)
silently collects **zero** tax while looking like it's working, which is the
single most common Stripe Tax mistake. If you need to charge tax, register
first, then add `automatic_tax={"enabled": True}` to the `checkout.Session.create`
call.

## What was verified this session vs. what still needs a live test

Done without a live secret key (none was shared with this assistant, by
design — see the security note below):

- Created the two real Products + Prices above via the Stripe MCP against
  your connected sandbox, and archived the earlier single-tier product.
- Upgraded the `stripe` Python SDK from `11.1.1` → `15.4.0` (latest) and
  pinned `stripe.api_version` explicitly in `billing_service.py` rather than
  floating with the account's Dashboard default.
- Added `integration_identifier` to the Checkout Session call per current
  Stripe guidance.
- Signed and POSTed synthetic webhook events against the real running
  webhook handler with a locally-generated signing secret — including the
  new plan-detection logic (`checkout.session.completed` with each tier's
  metadata, `customer.subscription.updated` with each tier's actual price
  ID) — and confirmed `Subscription.plan` and hosted-model eligibility come
  out correct for both tiers. See `PROGRESS.md` for the full transcript.

**Still needs a real end-to-end run once you set `STRIPE_SECRET_KEY` to an
actual key**: an actual Checkout redirect + test-card payment + a webhook
delivered by real Stripe infrastructure (rather than a locally-signed
stand-in) hitting a publicly reachable `/api/billing/webhook`, for both
tiers, plus the Customer Portal plan-switch flow (step 6/8 above — Portal
plan-switching can only be configured and tested against a real Dashboard,
not simulated). Nothing about the webhook code path differs between the
simulated and real webhook — signature verification doesn't care who signed
it correctly — but "the whole flow actually works when Stripe itself is on
the other end" is worth confirming once, per the checklist in step 7.

**Why I didn't just ask you for the key:** never paste a secret/restricted
key into a chat session — treat it like a password. Set it directly in
`.env` (or your platform's secrets vault in production) yourself.

## Notes on what's NOT built

- **More than two tiers** — adding a third would mean a third Product/Price,
  a third entry in `PLANS`/`_price_id_for_plan`/`_plan_from_price_id` in
  `billing_service.py`, and a third pricing card on the homepage/
  `/subscribe` — all mechanical extensions of the existing two-tier pattern,
  not a redesign.
- **Proration on plan switches** — handled entirely by Stripe's Customer
  Portal (step 6) once configured; no custom code needed. One simplification
  on our side: switching plans mid-period doesn't reset
  `tokens_used_current_period` (only a new billing period does), so a
  byok→hosted switch mid-cycle starts with whatever quota's left rather than
  a fresh full quota — self-corrects at the next `invoice.payment_succeeded`.
- **Free trials** — Stripe supports these natively on the Price object
  (`trial_period_days`); `Subscription.is_active()` already treats Stripe's
  `"trialing"` status as active, so turning one on in the Stripe Dashboard is
  all that's needed — no code changes.
