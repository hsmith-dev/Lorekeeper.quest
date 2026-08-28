from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# Resolve the project-root .env regardless of the working directory from which
# Python is invoked (e.g. `cd src/backend && pytest` vs `cd /repo && uvicorn …`).
# In the production Docker image the app is copied to a shallower directory
# tree (see Dockerfile.prod's `COPY . .` from a `./src/backend` build context),
# so this many parents may not exist there — that's fine, since
# docker-compose.prod.yml already injects everything via `env_file: .env`
# straight into the container's environment; this lookup is a local-dev
# convenience only and must never be fatal if the depth doesn't exist.
try:
    _ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"
except IndexError:
    _ROOT_ENV = Path(__file__).resolve().parent / ".env.not-found"


class Settings(BaseSettings):
    # Database
    database_url: str
    postgres_user: str = "lorekeeper"
    postgres_password: str
    postgres_db: str = "lorekeeper"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str
    access_token_expire_minutes: int = 1440
    refresh_token_expire_days: int = 7

    # KoboldCpp
    kobold_url: str = "http://localhost:5001"
    kobold_timeout_seconds: int = 120
    kobold_max_length: int = 800
    kobold_temperature: float = 0.72
    kobold_top_p: float = 0.95
    # Model name sent in the OpenAI-compat chat-completions fallback path
    # (see ai_service.generate_narrative / llm_provider._openai_compat) when
    # KOBOLD_URL points at Ollama rather than real KoboldCpp — KoboldCpp
    # ignores the "model" field entirely (it only ever serves whatever's
    # loaded), but Ollama's OpenAI-compat endpoint requires the exact name a
    # model was `ollama create`'d under (see scripts/deploy-oci.sh), or it
    # 404s. Harmless default for real KoboldCpp deployments either way.
    kobold_model: str = "lorekeeper"
    # The un-fine-tuned counterpart to kobold_model — same base architecture
    # (Mistral 7B Instruct), imported into the same Ollama instance under its
    # own name (see scripts/deploy-oci.sh's Ollama model import step and
    # src/ml/models/base-Modelfile). Lets a user pick "Base Model" instead of
    # "Fine-Tuned" in Settings' AI Provider section, and lets Model
    # Evaluation run the validation set against both and actually compare —
    # the capstone proposal's stretch goal, which previously only had the
    # fine-tuned model reachable anywhere in production.
    kobold_base_model: str = "lorekeeper-base"

    # App
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"
    # Self-host / free-community mode: registration grants full access
    # immediately (no promo code, no subscription), and the platform-default
    # LLM (your own Ollama) is available to every account with no billing
    # gate or token metering. Promo codes and Stripe (if configured) still
    # work alongside it, they're just not required. False preserves the
    # gated SaaS behavior.
    open_access_mode: bool = False
    # Base URL of the deployed frontend — used to build Stripe Checkout/Portal
    # success/cancel/return redirect URLs. Falls back to the dev Vite origin.
    frontend_url: str = "http://localhost:5173"

    # ── Billing (Stripe) ────────────────────────────────────────────────────
    # All optional so the app still boots (promo-code-only mode) if billing
    # isn't configured yet — app/api/routes/billing.py checks these are set
    # before doing anything Stripe-related and returns a clear 503 otherwise.
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    # Two tiers, two Products, two Prices — see stripe-best-practices: don't
    # put different tiers' prices on one Product, or every Checkout/invoice
    # line item shows the same Product name and a customer can't tell which
    # plan they're looking at. app/services/billing_service.py maps a Stripe
    # subscription's actual price ID back to "byok"/"hosted" — that mapping,
    # not what checkout was merely *requested* with, is the source of truth.
    stripe_price_id_byok: str | None = None    # $5/mo — bring your own LLM key
    stripe_price_id_hosted: str | None = None  # $15/mo — platform's hosted model, metered
    # Tokens (rough chars/4 estimate — see billing_service.estimate_tokens)
    # a "hosted" subscriber's period grants them against the platform model
    # before they need to supply their own API key for the rest of the period.
    # Not applicable to the "byok" tier, which never gets hosted-model access.
    subscription_monthly_token_quota: int = 1_000_000

    # ── Email (Resend) ──────────────────────────────────────────────────────
    # All optional so the app still boots and registration/reset-password
    # still work (just without sending anything) if email isn't configured
    # yet — see app/services/email_service.py, which logs a warning and
    # returns False rather than raising when resend_api_key is unset.
    resend_api_key: str | None = None
    # Must be an address on a domain verified in Resend's dashboard — an
    # unverified sender gets every send rejected by Resend before it ever
    # reaches an inbox. See docs/EMAIL_SETUP.md.
    resend_from_email: str = "Lorekeeper <noreply@lorekeeper.quest>"
    password_reset_token_expire_minutes: int = 60

    # ── Admin ────────────────────────────────────────────────────────────────
    # Single-operator admin check (see app/api/deps.py::require_admin) — no
    # role/permission table, just an email match against whoever's running
    # this instance. Unset by default so admin routes 403 for everyone until
    # deliberately configured; case-insensitive since email addresses are.
    admin_email: str | None = None

    class Config:
        env_file = str(_ROOT_ENV)
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
