from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.app_config import AppConfig


async def get_app_config(db: AsyncSession) -> AppConfig:
    """Fetch the singleton platform-config row, creating it if it's somehow
    missing (a restored pre-migration backup; a fresh DB where the migration
    seed was edited out). The initial value on that defensive-create path
    comes from the OPEN_ACCESS_MODE env var so an operator's explicit env
    choice is honored exactly once — after that the row is authoritative and
    edited from the admin portal."""
    result = await db.execute(select(AppConfig).where(AppConfig.id == 1))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        from app.core.config import get_settings
        cfg = AppConfig(id=1, open_access_mode=get_settings().open_access_mode)
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


async def is_open_access(db: AsyncSession) -> bool:
    """True when the platform runs unrestricted (see AppConfig's docstring).
    Consulted by registration (auth.py), the feature-route account gate
    (deps.require_active_account), and hosted-LLM access
    (deps.get_user_llm_config)."""
    return (await get_app_config(db)).open_access_mode
