from sqlalchemy import Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin


class AppConfig(Base, TimestampMixin):
    """Singleton row (id=1) of operator-tunable platform settings, editable
    live from the admin portal — no redeploy or env change needed. The
    migration that creates this table seeds the row, so it can be assumed to
    exist; app_config_service.get_app_config() re-creates it defensively if
    it's ever missing (e.g. a restored backup from before the migration).

    open_access_mode: True (the default) = anyone can register and use the
    app, including the self-hosted model, with no promo code, subscription,
    billing gate, or metering — the right mode for self-hosting, a company
    provisioning accounts for its users, or a free community server. False =
    gated SaaS mode: accounts need a promo code or Stripe subscription
    (docs/PAYMENT_PROCESSOR_SETUP.md). The OPEN_ACCESS_MODE env var is only
    the seed/fallback value; this row is authoritative once it exists."""

    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    open_access_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
