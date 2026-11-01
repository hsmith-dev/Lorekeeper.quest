from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime

from app.domain.enums import CampaignRole, Visibility


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _values(enum_cls):
    return [m.value for m in enum_cls]


# The two Postgres enum types (AD-12). The F1-core revision (c95acb56c595)
# creates them; the models never emit CREATE TYPE. Stored values are the
# StrEnum values, not the member names.
VISIBILITY_ENUM = ENUM(Visibility, name="visibility", create_type=False, values_callable=_values)
CAMPAIGN_ROLE_ENUM = ENUM(CampaignRole, name="campaign_role", create_type=False, values_callable=_values)
