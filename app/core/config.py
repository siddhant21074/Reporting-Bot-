"""Centralized configuration for the application.

Configuration resolves in three layers, highest priority first:

1. Runtime overrides   -- values saved from the admin Settings page (see
                          ``apply_runtime_overrides``). Held in memory and
                          reloaded from the database at startup.
2. Environment / .env  -- the ``Settings`` fields below.
3. Field defaults      -- the ``Field(default=...)`` values.

Grouped accessors (``settings.whatsapp``, ``settings.telegram``, ``settings.llm``,
``settings.stt``) read through all three layers, so changing a credential from the
UI takes effect without a redeploy.
"""

import os
import threading
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Runtime override layer (written by the admin Settings page)
# ---------------------------------------------------------------------------

_overrides: Dict[str, Any] = {}
_overrides_lock = threading.RLock()

# Keys that must never be echoed back to the UI in full.
SECRET_KEYS = frozenset({
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "LLM_API_KEY",
    "STT_API_KEY",
    "ADMIN_PASSWORD_HASH",
    "SECRET_KEY",
})


def apply_runtime_overrides(values: Dict[str, Any]) -> None:
    """Merges values saved from the admin UI over the environment configuration.

    Args:
        values: Mapping of ``Settings`` field names to values. A value of ``None``
            or ``""`` clears the override and falls back to the environment.
    """
    with _overrides_lock:
        for key, value in values.items():
            if value is None or value == "":
                _overrides.pop(key, None)
            else:
                _overrides[key] = value


def clear_runtime_overrides() -> None:
    """Drops every runtime override, reverting to environment configuration."""
    with _overrides_lock:
        _overrides.clear()


def get_runtime_overrides() -> Dict[str, Any]:
    """Returns a copy of the current runtime override map."""
    with _overrides_lock:
        return dict(_overrides)


# ---------------------------------------------------------------------------
# Grouped configuration models
# ---------------------------------------------------------------------------


class AppSettings(BaseModel):
    """Application-wide settings."""
    name: str
    version: str
    environment: str
    log_level: str
    debug: bool
    base_url: str
    database_url: str
    redis_url: str
    logs_dir: str
    media_dir: str
    reports_dir: str
    temp_dir: str
    fonts_dir: str
    http_timeout: int
    http_retry_count: int
    retention_days: int
    session_timeout_seconds: int


class AdminSettings(BaseModel):
    """Credentials and signing material for the admin dashboard."""
    username: str
    password_hash: str
    secret_key: str
    session_max_age: int

    @property
    def is_configured(self) -> bool:
        """True when an admin login can actually be performed."""
        return bool(self.username and self.password_hash and self.secret_key)


class WhatsAppSettings(BaseModel):
    """Meta WhatsApp Cloud API settings."""
    enabled: bool
    access_token: str
    phone_number_id: str
    verify_token: str
    app_secret: str
    api_version: str
    app_id: str
    business_account_id: str
    webhook_url: str
    phone_number: str

    @property
    def is_configured(self) -> bool:
        """True when the channel has everything it needs to send and verify."""
        return bool(self.access_token and self.phone_number_id and self.verify_token and self.app_secret)


class TelegramSettings(BaseModel):
    """Telegram Bot API settings."""
    enabled: bool
    bot_token: str
    webhook_secret: str
    api_base_url: str

    @property
    def is_configured(self) -> bool:
        """True when the bot token is present."""
        return bool(self.bot_token)


class ModelSettings(BaseModel):
    """Resolved settings for one AI role (chat structuring or speech-to-text)."""
    provider: str
    model: str
    api_key: str
    base_url: Optional[str]
    timeout: float

    @property
    def is_configured(self) -> bool:
        """True when the provider can be called.

        Local providers (Ollama, faster-whisper) need no key.
        """
        from app.ai.registry import provider_requires_key

        if provider_requires_key(self.provider):
            return bool(self.api_key)
        return True


# ---------------------------------------------------------------------------
# Environment-backed settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Central configuration loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ------------------------------------------------------
    APP_NAME: str = Field(default="SiteReport Bot")
    APP_VERSION: str = Field(default="0.2.0")
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    DEBUG: bool = Field(default=False)
    BASE_URL: str = Field(default="http://localhost:8000", description="Public base URL, used to build webhook URLs.")

    # --- Storage ----------------------------------------------------------
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///storage/app.db")
    REDIS_URL: str = Field(default="")
    LOG_STORAGE_PATH: str = Field(default="storage/logs")
    MEDIA_STORAGE_PATH: str = Field(default="storage/media")
    REPORT_STORAGE_PATH: str = Field(default="storage/reports")
    STORAGE_TEMP_DIR: str = Field(default="storage/temp")
    FONTS_DIR: str = Field(default="storage/fonts")

    # --- Retention & sessions --------------------------------------------
    RETENTION_DAYS: int = Field(default=7, description="How long messages, reports and media are kept.")
    SESSION_TIMEOUT_SECONDS: int = Field(default=1800)

    # --- Admin dashboard --------------------------------------------------
    ADMIN_USERNAME: str = Field(default="admin")
    ADMIN_PASSWORD_HASH: str = Field(default="", description="bcrypt hash. Generate with scripts/make_admin.py.")
    SECRET_KEY: str = Field(default="", description="Signs admin session cookies. Required in production.")
    ADMIN_SESSION_MAX_AGE: int = Field(default=28800)

    # --- Channel: WhatsApp (Meta Cloud API) -------------------------------
    WHATSAPP_ENABLED: bool = Field(default=True)
    WHATSAPP_APP_ID: str = Field(default="")
    WHATSAPP_APP_SECRET: str = Field(default="")
    WHATSAPP_ACCESS_TOKEN: str = Field(default="")
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = Field(default="")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="")
    WHATSAPP_PHONE_NUMBER: str = Field(default="")
    WHATSAPP_VERIFY_TOKEN: str = Field(default="")
    META_API_VERSION: str = Field(default="v21.0")
    WHATSAPP_WEBHOOK_URL: str = Field(default="")

    # --- Channel: Telegram ------------------------------------------------
    TELEGRAM_ENABLED: bool = Field(default=False)
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_WEBHOOK_SECRET: str = Field(default="", description="Sent back as X-Telegram-Bot-Api-Secret-Token.")
    TELEGRAM_API_BASE_URL: str = Field(default="https://api.telegram.org")

    # --- AI: chat / structuring -------------------------------------------
    LLM_PROVIDER: str = Field(default="openai", description="openai | openrouter | groq | together | deepinfra | ollama | custom")
    LLM_MODEL: str = Field(default="gpt-4o-mini")
    LLM_API_KEY: str = Field(default="")
    LLM_BASE_URL: str = Field(default="", description="Only needed for provider=custom, or to override a known provider.")
    LLM_TIMEOUT: float = Field(default=60.0)

    # --- AI: speech-to-text ------------------------------------------------
    STT_PROVIDER: str = Field(default="openai", description="openai | groq | deepinfra | faster-whisper | google-web | custom")
    STT_MODEL: str = Field(default="whisper-1")
    STT_API_KEY: str = Field(default="", description="Falls back to LLM_API_KEY when the provider is the same.")
    STT_BASE_URL: str = Field(default="")
    STT_TIMEOUT: float = Field(default=120.0)
    STT_LANGUAGE: str = Field(default="", description="ISO code hint, e.g. 'en' or 'hi'. Blank = auto-detect.")

    # --- Legacy keys, still honoured as fallbacks -------------------------
    OPENAI_API_KEY: str = Field(default="")
    OPENROUTER_API_KEY: str = Field(default="")
    OPENAI_MODEL_NAME: str = Field(default="")
    AI_PROVIDER: str = Field(default="")

    # --- HTTP client ------------------------------------------------------
    HTTP_TIMEOUT: int = Field(default=30)
    HTTP_RETRY_COUNT: int = Field(default=3)

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _get(self, key: str) -> Any:
        """Reads a field through the runtime override layer."""
        with _overrides_lock:
            if key in _overrides:
                return _overrides[key]
        return getattr(self, key)

    def _str(self, key: str) -> str:
        value = self._get(key)
        return "" if value is None else str(value)

    def _bool(self, key: str) -> bool:
        value = self._get(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _int(self, key: str) -> int:
        return int(self._get(key))

    def _float(self, key: str) -> float:
        return float(self._get(key))

    # ------------------------------------------------------------------
    # Grouped accessors
    # ------------------------------------------------------------------

    @property
    def app(self) -> AppSettings:
        """Application-wide configuration."""
        return AppSettings(
            name=self._str("APP_NAME"),
            version=self._str("APP_VERSION"),
            environment=self._str("ENVIRONMENT"),
            log_level=self._str("LOG_LEVEL"),
            debug=self._bool("DEBUG"),
            base_url=self._str("BASE_URL").rstrip("/"),
            database_url=self._str("DATABASE_URL"),
            redis_url=self._str("REDIS_URL"),
            logs_dir=self._str("LOG_STORAGE_PATH"),
            media_dir=self._str("MEDIA_STORAGE_PATH"),
            reports_dir=self._str("REPORT_STORAGE_PATH"),
            temp_dir=self._str("STORAGE_TEMP_DIR"),
            fonts_dir=self._str("FONTS_DIR"),
            http_timeout=self._int("HTTP_TIMEOUT"),
            http_retry_count=self._int("HTTP_RETRY_COUNT"),
            retention_days=self._int("RETENTION_DAYS"),
            session_timeout_seconds=self._int("SESSION_TIMEOUT_SECONDS"),
        )

    @property
    def admin(self) -> AdminSettings:
        """Admin dashboard credentials."""
        return AdminSettings(
            username=self._str("ADMIN_USERNAME"),
            password_hash=self._str("ADMIN_PASSWORD_HASH"),
            secret_key=self._str("SECRET_KEY"),
            session_max_age=self._int("ADMIN_SESSION_MAX_AGE"),
        )

    @property
    def whatsapp(self) -> WhatsAppSettings:
        """Meta WhatsApp Cloud API configuration."""
        return WhatsAppSettings(
            enabled=self._bool("WHATSAPP_ENABLED"),
            access_token=self._str("WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=self._str("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=self._str("WHATSAPP_VERIFY_TOKEN"),
            app_secret=self._str("WHATSAPP_APP_SECRET"),
            api_version=self._str("META_API_VERSION"),
            app_id=self._str("WHATSAPP_APP_ID"),
            business_account_id=self._str("WHATSAPP_BUSINESS_ACCOUNT_ID"),
            webhook_url=self._str("WHATSAPP_WEBHOOK_URL") or f"{self._str('BASE_URL').rstrip('/')}/webhook/whatsapp",
            phone_number=self._str("WHATSAPP_PHONE_NUMBER"),
        )

    @property
    def telegram(self) -> TelegramSettings:
        """Telegram Bot API configuration."""
        return TelegramSettings(
            enabled=self._bool("TELEGRAM_ENABLED"),
            bot_token=self._str("TELEGRAM_BOT_TOKEN"),
            webhook_secret=self._str("TELEGRAM_WEBHOOK_SECRET"),
            api_base_url=self._str("TELEGRAM_API_BASE_URL").rstrip("/"),
        )

    @property
    def llm(self) -> ModelSettings:
        """Chat/structuring model configuration."""
        from app.ai.registry import resolve_base_url

        provider = (self._str("LLM_PROVIDER") or self._str("AI_PROVIDER") or "openai").strip().lower()
        api_key = self._str("LLM_API_KEY") or self._legacy_key_for(provider)
        model = self._str("LLM_MODEL") or self._str("OPENAI_MODEL_NAME") or "gpt-4o-mini"

        return ModelSettings(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=self._str("LLM_BASE_URL") or resolve_base_url(provider),
            timeout=self._float("LLM_TIMEOUT"),
        )

    @property
    def stt(self) -> ModelSettings:
        """Speech-to-text model configuration."""
        from app.ai.registry import resolve_base_url

        provider = (self._str("STT_PROVIDER") or "openai").strip().lower()
        llm = self.llm

        # Reuse the chat key when both roles point at the same provider.
        api_key = self._str("STT_API_KEY") or (llm.api_key if provider == llm.provider else "")
        if not api_key:
            api_key = self._legacy_key_for(provider)

        return ModelSettings(
            provider=provider,
            model=self._str("STT_MODEL") or "whisper-1",
            api_key=api_key,
            base_url=self._str("STT_BASE_URL") or resolve_base_url(provider),
            timeout=self._float("STT_TIMEOUT"),
        )

    @property
    def stt_language(self) -> Optional[str]:
        """Optional ISO language hint for transcription."""
        return self._str("STT_LANGUAGE").strip() or None

    def _legacy_key_for(self, provider: str) -> str:
        """Falls back to the pre-0.2 environment variable names."""
        if provider == "openrouter":
            return self._str("OPENROUTER_API_KEY") or os.getenv("OPEN_ROUTER_API", "")
        if provider == "openai":
            return self._str("OPENAI_API_KEY")
        return os.getenv(f"{provider.upper().replace('-', '_')}_API_KEY", "")


# Global settings instance
settings = Settings()
