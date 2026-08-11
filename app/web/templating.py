"""Jinja environment, filters and shared view helpers."""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.core.config import settings

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def when(value: Optional[datetime]) -> str:
    """Formats a timestamp as a short relative time, falling back to a date."""
    if not value:
        return "—"

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    delta = datetime.now(timezone.utc) - value
    seconds = delta.total_seconds()

    if seconds < 0:
        return value.strftime("%d %b %H:%M")
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hr ago" if hours > 1 else "1 hr ago"
    if seconds < 604800:
        days = int(seconds // 86400)
        return f"{days} days ago" if days > 1 else "yesterday"
    return value.strftime("%d %b %Y")


def statelabel(value: Any) -> str:
    """Turns a workflow state constant into something a person can read."""
    labels = {
        "IDLE": "Idle",
        "WAITING_FOR_INPUT": "Awaiting update",
        "WAITING_FOR_PHOTOS": "Adding photos",
        "WAITING_FOR_CONFIRMATION": "Reviewing draft",
        "GENERATING_REPORT": "Building report",
        "REPORT_GENERATED": "Report sent",
        "CANCELLED": "Cancelled",
    }
    key = getattr(value, "value", value)
    return labels.get(str(key), str(key).replace("_", " ").title())


# ---------------------------------------------------------------------------
# Template globals
# ---------------------------------------------------------------------------


def status_pill(status: Any) -> Markup:
    """Renders a report status as a coloured pill.

    The colour never carries the meaning on its own -- the word is always there
    beside it.
    """
    value = getattr(status, "value", str(status))
    css, label = {
        "delivered": ("pill-good", "Delivered"),
        "failed": ("pill-critical", "Failed"),
        "generating": ("pill-warning", "Building"),
    }.get(value, ("", value.title()))
    return Markup(f'<span class="pill {css}"><span class="dot"></span>{label}</span>')


def health_pill(state: Dict[str, Any]) -> Markup:
    """Renders a system-status entry as a pill with its own label."""
    css = {"ok": "pill-good", "warn": "pill-warning", "bad": "pill-critical"}.get(state.get("level", ""), "")
    label = state.get("label", "Unknown")
    title = state.get("detail", "")
    attr = f' title="{title}"' if title else ""
    return Markup(f'<span class="pill {css}"{attr}><span class="dot"></span>{label}</span>')


def make_qs(request: Request):
    """Returns a helper that rebuilds the current query string with overrides.

    Lets pagination links keep the active search and filters.
    """

    def qs(**overrides: Any) -> str:
        params = dict(request.query_params)
        for key, value in overrides.items():
            if value in (None, ""):
                params.pop(key, None)
            else:
                params[key] = str(value)
        return urlencode(params)

    return qs


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------


def system_health() -> Dict[str, Dict[str, Any]]:
    """Checks everything the dashboard reports on.

    Each entry is ``{"level": ok|warn|bad, "label": str, "detail": str}``. The
    label always states the condition in words -- the colour is secondary.
    """
    from app.ai.registry import provider_info
    from app.reports.fonts import get_fonts

    whatsapp = settings.whatsapp
    telegram = settings.telegram
    llm = settings.llm
    stt = settings.stt

    def channel_state(config, name: str) -> Dict[str, Any]:
        if not config.enabled:
            return {"level": "", "label": "Off", "detail": f"{name} is switched off."}
        if not config.is_configured:
            return {"level": "warn", "label": "Incomplete", "detail": f"{name} is on but missing credentials."}
        return {"level": "ok", "label": "Connected", "detail": f"{name} is configured."}

    def model_state(config, role: str) -> Dict[str, Any]:
        label = provider_info(config.provider)["label"]
        if not config.is_configured:
            return {
                "level": "bad",
                "label": "No key",
                "detail": f"{label} needs an API key before {role} will work.",
            }
        return {"level": "ok", "label": f"{label} · {config.model}", "detail": f"{role} via {label}."}

    def stt_state() -> Dict[str, Any]:
        """Reports the engine transcription will actually use.

        A built-in fallback is working, but it is not what was configured, so
        it reads as a warning rather than a clean pass.
        """
        from app.ai import AIProvider

        described = AIProvider().describe()["stt"]

        if described["effective"] is None:
            return {
                "level": "bad",
                "label": "Unavailable",
                "detail": described["reason"]
                + ". Add a key on this page, or run: pip install faster-whisper",
            }

        if described["provider"] == "auto":
            return {
                "level": "warn",
                "label": f"Built-in · {described['effective_label']}",
                "detail": "Set to automatic, so transcription uses the built-in engine. "
                          "A hosted provider would be more accurate.",
            }

        if described["is_fallback"]:
            return {
                "level": "warn",
                "label": f"Built-in · {described['effective_label']}",
                "detail": f"Fell back to the built-in engine because {described['reason']}. "
                          "Add an API key for better accuracy.",
            }

        return {
            "level": "ok",
            "label": f"{described['label']} · {described['model']}",
            "detail": f"Transcription via {described['label']}.",
        }

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        try:
            import imageio_ffmpeg

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_path = None

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    fonts = get_fonts()

    return {
        "whatsapp": channel_state(whatsapp, "WhatsApp"),
        "telegram": channel_state(telegram, "Telegram"),
        "llm": model_state(llm, "report writing"),
        "stt": stt_state(),
        "ffmpeg": (
            {"level": "ok", "label": "Available", "detail": f"ffmpeg at {ffmpeg_path}"}
            if ffmpeg_path
            else {"level": "bad", "label": "Missing", "detail": "Voice notes cannot be decoded without ffmpeg."}
        ),
        "libreoffice": (
            {"level": "ok", "label": "Exact template", "detail": "LibreOffice converts the Word template to PDF."}
            if soffice
            else {
                "level": "warn",
                "label": "Built-in renderer",
                "detail": "LibreOffice is not installed, so PDFs do not match the Word template exactly.",
            }
        ),
        "fonts": (
            {"level": "ok", "label": fonts.family, "detail": "Unicode text renders correctly in PDFs."}
            if fonts.unicode
            else {
                "level": "warn",
                "label": "Latin only",
                "detail": "No Unicode font found; non-Latin text is transliterated in PDFs.",
            }
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(
    request: Request,
    template: str,
    user: Any,
    page_title: str,
    active: str = "",
    page_sub: str = "",
    flash: Optional[Dict[str, str]] = None,
    **context: Any,
):
    """Renders a page with the shell context every template expects."""
    base = {
        "request": request,
        "user": user,
        "page_title": page_title,
        "page_sub": page_sub,
        "active": active,
        "flash": flash,
        "app_name": settings.app.name,
        "environment": settings.app.environment.title(),
        "year": datetime.now().year,
        # Light is the default everywhere; dark is opt-in via the sidebar toggle.
        "theme": "light",
        "status_pill": status_pill,
        "health_pill": health_pill,
        "qs": make_qs(request),
    }
    base.update(context)
    return templates.TemplateResponse(template, base)


def flash_from_query(request: Request) -> Optional[Dict[str, str]]:
    """Builds a flash message from ``?ok=`` or ``?err=`` after a redirect.

    Post/redirect/get avoids re-submitting a form on refresh, and this carries
    the outcome across the redirect without a session store.
    """
    ok = request.query_params.get("ok")
    err = request.query_params.get("err")
    if ok:
        return {"kind": "ok", "title": ok, "detail": ""}
    if err:
        return {"kind": "error", "title": err, "detail": ""}
    return None


def register(app) -> None:
    """Installs the filters and mounts the static directory."""
    from fastapi.staticfiles import StaticFiles

    templates.env.filters["when"] = when
    templates.env.filters["statelabel"] = statelabel
    templates.env.filters["min"] = min

    os.makedirs(STATIC_DIR, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
