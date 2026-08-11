"""Persistence for values edited on the Settings page.

Saved values are layered over the environment by
``app.core.config.apply_runtime_overrides``, so a credential or model changed in
the UI takes effect immediately and again after a restart.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SECRET_KEYS, apply_runtime_overrides
from app.db.models import AppSetting, utcnow

logger = logging.getLogger("app.repositories.settings")

# Only these may be written from the UI. Anything else -- database URL, storage
# paths, the cookie signing key -- stays in .env where a web request cannot
# reach it.
EDITABLE_KEYS: List[str] = [
    # WhatsApp
    "WHATSAPP_ENABLED",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "WHATSAPP_APP_ID",
    "WHATSAPP_PHONE_NUMBER",
    "META_API_VERSION",
    # Telegram
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    # Chat model
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TIMEOUT",
    # Speech-to-text
    "STT_PROVIDER",
    "STT_MODEL",
    "STT_API_KEY",
    "STT_BASE_URL",
    "STT_TIMEOUT",
    "STT_LANGUAGE",
    # General
    "RETENTION_DAYS",
    "SESSION_TIMEOUT_SECONDS",
    "BASE_URL",
]

# Shown as "configured" rather than echoed back to the browser.
MASKED_VALUE = "********"


async def load_overrides(db: AsyncSession) -> int:
    """Applies every saved setting to the live configuration.

    Called at startup so UI changes survive a restart.

    Returns:
        The number of settings applied.
    """
    rows = (await db.execute(select(AppSetting))).scalars().all()
    values = {row.key: row.value for row in rows if row.key in EDITABLE_KEYS}

    if values:
        apply_runtime_overrides(values)
        logger.info(
            f"Applied {len(values)} saved setting(s) from the database.",
            extra={"event": "settings_loaded", "count": len(values)},
        )
    return len(values)


async def save_settings(
    db: AsyncSession,
    values: Dict[str, str],
    actor: str,
) -> List[str]:
    """Persists settings and applies them immediately.

    A submitted value equal to ``MASKED_VALUE`` means "leave this secret alone",
    which is what the form sends back for a field the browser never saw.

    Args:
        db: Session.
        values: Submitted key/value pairs.
        actor: Username making the change, recorded against each row.

    Returns:
        The keys that actually changed.
    """
    existing = {row.key: row for row in (await db.execute(select(AppSetting))).scalars().all()}
    changed: List[str] = []

    for key, raw in values.items():
        if key not in EDITABLE_KEYS:
            continue

        value = (raw or "").strip()
        is_secret = key in SECRET_KEYS

        if is_secret and value == MASKED_VALUE:
            continue

        current = existing.get(key)
        if current is not None and (current.value or "") == value:
            continue

        if value == "":
            # Clearing a setting falls back to whatever .env says.
            if current is not None:
                await db.delete(current)
                changed.append(key)
            continue

        if current is None:
            db.add(AppSetting(key=key, value=value, is_secret=is_secret, updated_by=actor))
        else:
            current.value = value
            current.is_secret = is_secret
            current.updated_by = actor
            current.updated_at = utcnow()
        changed.append(key)

    await db.flush()

    if changed:
        # Reload the whole set so cleared keys revert rather than linger.
        from app.core.config import clear_runtime_overrides

        clear_runtime_overrides()
        await load_overrides(db)

        logger.info(
            f"'{actor}' updated {len(changed)} setting(s): {', '.join(sorted(changed))}",
            extra={"event": "settings_saved", "actor": actor, "keys": sorted(changed)},
        )

    return changed


async def clear_setting(db: AsyncSession, key: str) -> bool:
    """Removes one saved setting so the environment value takes over again."""
    if key not in EDITABLE_KEYS:
        return False

    await db.execute(delete(AppSetting).where(AppSetting.key == key))
    await db.flush()

    from app.core.config import clear_runtime_overrides

    clear_runtime_overrides()
    await load_overrides(db)
    return True


async def saved_keys(db: AsyncSession) -> Dict[str, Optional[str]]:
    """Returns which keys are stored in the database and when they changed.

    Lets the Settings page distinguish "set here" from "inherited from .env".
    """
    rows = (await db.execute(select(AppSetting))).scalars().all()
    return {
        row.key: row.updated_at.strftime("%d %b %Y, %H:%M") if row.updated_at else None
        for row in rows
    }
