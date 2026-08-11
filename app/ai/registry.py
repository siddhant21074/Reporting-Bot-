"""Catalogue of AI providers and models available to the bot.

Every provider here speaks the OpenAI wire format, so a single ``AsyncOpenAI``
client drives all of them -- only the base URL and the API key change. That is
what lets the Settings page offer free and paid models side by side.

Two roles are configured independently:

* ``chat`` -- structures a transcript into the report schema.
* ``stt``  -- turns a voice note into text.

Model lists are fetched live from each provider's ``GET /models`` endpoint, so a
newly released model is selectable without a code change. ``FALLBACK_MODELS``
is only used when that call fails or no key is set yet.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("app.ai.registry")

CHAT = "chat"
STT = "stt"


class ProviderInfo(Dict[str, Any]):
    """Marker type for provider metadata dictionaries."""


# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
        "roles": [CHAT, STT],
        "models_endpoint": True,
        "key_url": "https://platform.openai.com/api-keys",
        "note": "Paid. Best structuring quality; whisper-1 and gpt-4o-transcribe for voice.",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "requires_key": True,
        "roles": [CHAT],
        "models_endpoint": True,
        "key_url": "https://openrouter.ai/keys",
        "note": "One key for Claude, Gemini, Llama, Mistral, DeepSeek and Qwen. "
                "Models ending in ':free' cost nothing.",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "requires_key": True,
        "roles": [CHAT, STT],
        "models_endpoint": True,
        "key_url": "https://console.groq.com/keys",
        "note": "Generous free tier and very fast. whisper-large-v3 makes it a good "
                "no-cost speech-to-text option.",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "requires_key": True,
        "roles": [CHAT],
        "models_endpoint": True,
        "key_url": "https://api.together.xyz/settings/api-keys",
        "note": "Open-weight models, some free endpoints.",
    },
    "deepinfra": {
        "label": "DeepInfra",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "requires_key": True,
        "roles": [CHAT, STT],
        "models_endpoint": True,
        "key_url": "https://deepinfra.com/dash/api_keys",
        "note": "Low-cost open-weight chat and Whisper.",
    },
    "ollama": {
        "label": "Ollama (self-hosted)",
        "base_url": "http://localhost:11434/v1",
        "requires_key": False,
        "roles": [CHAT],
        "models_endpoint": True,
        "key_url": "https://ollama.com/download",
        "note": "Free and fully local. Runs on the same droplet; needs RAM, no key.",
    },
    "auto": {
        "label": "Automatic (built-in, no key)",
        "base_url": None,
        "requires_key": False,
        "roles": [STT],
        "models_endpoint": False,
        "key_url": "",
        "note": "Uses whichever speech library is installed, best first: "
                "faster-whisper, then PocketSphinx, then Google Web Speech. "
                "This is also the automatic fallback whenever the chosen "
                "provider has no API key.",
    },
    "faster-whisper": {
        "label": "faster-whisper (local)",
        "base_url": None,
        "requires_key": False,
        "roles": [STT],
        "models_endpoint": False,
        "key_url": "https://github.com/SYSTRAN/faster-whisper",
        "note": "Free and fully local speech-to-text. No network call, no per-minute cost. "
                "Install with: pip install faster-whisper",
    },
    "sphinx": {
        "label": "PocketSphinx (local)",
        "base_url": None,
        "requires_key": False,
        "roles": [STT],
        "models_endpoint": False,
        "key_url": "https://pypi.org/project/pocketsphinx/",
        "note": "Free, fully offline and lightweight, through the SpeechRecognition "
                "library the project already depends on. English only and noticeably "
                "less accurate than Whisper. Install with: pip install pocketsphinx",
    },
    "google-web": {
        "label": "Google Web Speech (legacy)",
        "base_url": None,
        "requires_key": False,
        "roles": [STT],
        "models_endpoint": False,
        "key_url": "",
        "note": "Free but unofficial and rate-limited. Kept for backwards compatibility "
                "only -- not recommended for production.",
        "deprecated": True,
    },
    "custom": {
        "label": "Custom OpenAI-compatible endpoint",
        "base_url": None,
        "requires_key": False,
        "roles": [CHAT, STT],
        "models_endpoint": True,
        "key_url": "",
        "note": "Point at any OpenAI-compatible server by setting the base URL.",
    },
}


# Offered when the live /models call is unavailable. Not exhaustive -- the
# Settings page always allows typing a model ID by hand.
FALLBACK_MODELS: Dict[str, Dict[str, List[str]]] = {
    "openai": {
        CHAT: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
        STT: ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"],
    },
    "openrouter": {
        CHAT: [
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat-v3:free",
            "qwen/qwen-2.5-72b-instruct:free",
        ],
        STT: [],
    },
    "groq": {
        CHAT: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        STT: ["whisper-large-v3", "whisper-large-v3-turbo"],
    },
    "together": {CHAT: ["meta-llama/Llama-3.3-70B-Instruct-Turbo"], STT: []},
    "deepinfra": {
        CHAT: ["meta-llama/Llama-3.3-70B-Instruct"],
        STT: ["openai/whisper-large-v3"],
    },
    "ollama": {CHAT: ["llama3.1", "qwen2.5", "mistral"], STT: []},
    "auto": {CHAT: [], STT: ["default"]},
    "faster-whisper": {CHAT: [], STT: ["tiny", "base", "small", "medium", "large-v3"]},
    "sphinx": {CHAT: [], STT: ["default"]},
    "google-web": {CHAT: [], STT: ["default"]},
    "custom": {CHAT: [], STT: []},
}


# ---------------------------------------------------------------------------
# Built-in speech-to-text, for when no API key is configured
# ---------------------------------------------------------------------------

# Tried in order. Each entry is (provider id, module that must import).
# faster-whisper is by far the most accurate; PocketSphinx is tiny and fully
# offline; Google Web Speech needs no install but does need internet and is an
# unofficial endpoint, so it sits last.
LOCAL_STT_CHAIN = (
    ("faster-whisper", "faster_whisper"),
    ("sphinx", "pocketsphinx"),
    ("google-web", "speech_recognition"),
)

_local_stt_cache: Optional[str] = None
_local_stt_resolved = False


def detect_local_stt(refresh: bool = False) -> Optional[str]:
    """Returns the best key-free speech-to-text engine installed, or ``None``.

    Import checks are cached: this runs on every voice note otherwise.

    Args:
        refresh: Re-probe instead of using the cached answer.
    """
    global _local_stt_cache, _local_stt_resolved

    if _local_stt_resolved and not refresh:
        return _local_stt_cache

    import importlib.util

    _local_stt_cache = None
    for provider_id, module_name in LOCAL_STT_CHAIN:
        try:
            if importlib.util.find_spec(module_name) is not None:
                _local_stt_cache = provider_id
                break
        except (ImportError, ValueError):
            continue

    _local_stt_resolved = True

    if _local_stt_cache:
        logger.info(
            f"Built-in speech-to-text available via '{_local_stt_cache}'.",
            extra={"event": "local_stt_detected", "provider": _local_stt_cache},
        )
    else:
        logger.warning(
            "No built-in speech-to-text library is installed. Voice notes need "
            "an API key, or: pip install faster-whisper",
            extra={"event": "local_stt_unavailable"},
        )

    return _local_stt_cache


def local_stt_label() -> str:
    """Human-readable name of the built-in engine, for the dashboard."""
    provider_id = detect_local_stt()
    return provider_info(provider_id)["label"] if provider_id else "none installed"


def is_local_stt(provider: str) -> bool:
    """True when a provider is one of the key-free built-in engines."""
    return provider in {pid for pid, _ in LOCAL_STT_CHAIN}


def local_stt_importable(provider: str) -> bool:
    """Whether a built-in engine's library is actually installed.

    Selecting ``faster-whisper`` in the UI does not install it, so this is
    checked before the engine is used rather than failing on the first voice
    note.
    """
    import importlib.util

    module = next((mod for pid, mod in LOCAL_STT_CHAIN if pid == provider), None)
    if module is None:
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def provider_info(provider: str) -> Dict[str, Any]:
    """Returns metadata for a provider, or the ``custom`` entry if unknown."""
    return PROVIDERS.get((provider or "").strip().lower(), PROVIDERS["custom"])


def resolve_base_url(provider: str) -> Optional[str]:
    """Returns the default base URL for a provider, or ``None`` for local ones."""
    return provider_info(provider).get("base_url")


def provider_requires_key(provider: str) -> bool:
    """True when the provider cannot be called without an API key."""
    return bool(provider_info(provider).get("requires_key"))


def providers_for_role(role: str) -> List[Dict[str, Any]]:
    """Lists providers that can serve a given role, for the Settings dropdowns.

    Args:
        role: Either ``CHAT`` or ``STT``.

    Returns:
        A list of ``{"id", "label", "note", "requires_key", "key_url", "deprecated"}``
        dictionaries.
    """
    out: List[Dict[str, Any]] = []
    for provider_id, info in PROVIDERS.items():
        if role not in info["roles"]:
            continue
        out.append({
            "id": provider_id,
            "label": info["label"],
            "note": info["note"],
            "requires_key": info["requires_key"],
            "key_url": info["key_url"],
            "deprecated": info.get("deprecated", False),
        })
    return out


def fallback_models(provider: str, role: str) -> List[str]:
    """Returns the static model suggestions for a provider and role."""
    return list(FALLBACK_MODELS.get((provider or "").strip().lower(), {}).get(role, []))


# ---------------------------------------------------------------------------
# Live model discovery
# ---------------------------------------------------------------------------

# Substrings that identify a transcription model in a mixed /models listing.
_STT_HINTS = ("whisper", "transcribe", "speech-to-text")


async def list_models(
    provider: str,
    api_key: str = "",
    base_url: Optional[str] = None,
    role: str = CHAT,
    http_client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Fetches the models a provider currently offers.

    Args:
        provider: Provider id from ``PROVIDERS``.
        api_key: Key for the provider, if it needs one.
        base_url: Overrides the provider's default base URL.
        role: ``CHAT`` or ``STT`` -- filters the returned list.
        http_client: Optional shared client; one is created if omitted.

    Returns:
        A list of ``{"id", "label", "free"}`` dictionaries, sorted with free
        models first. Falls back to ``FALLBACK_MODELS`` if discovery fails.
    """
    info = provider_info(provider)
    url_root = (base_url or info.get("base_url") or "").rstrip("/")

    if not info.get("models_endpoint") or not url_root:
        return [{"id": m, "label": m, "free": True} for m in fallback_models(provider, role)]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        if http_client is not None:
            response = await http_client.get(f"{url_root}/models", headers=headers, timeout=15.0)
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{url_root}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(
            f"Model discovery failed for provider '{provider}': {exc}. Using the static list.",
            extra={"event": "model_discovery_failed", "provider": provider},
        )
        return [{"id": m, "label": m, "free": True} for m in fallback_models(provider, role)]

    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return [{"id": m, "label": m, "free": True} for m in fallback_models(provider, role)]

    models: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id") or entry.get("name")
        if not model_id:
            continue

        looks_like_stt = any(hint in str(model_id).lower() for hint in _STT_HINTS)
        if role == STT and not looks_like_stt:
            continue
        if role == CHAT and looks_like_stt:
            continue

        models.append({
            "id": model_id,
            "label": entry.get("name") or model_id,
            "free": _is_free(entry, model_id),
        })

    if not models:
        return [{"id": m, "label": m, "free": True} for m in fallback_models(provider, role)]

    models.sort(key=lambda m: (not m["free"], str(m["id"]).lower()))
    return models


def _is_free(entry: Dict[str, Any], model_id: str) -> bool:
    """Determines whether a discovered model costs nothing to call.

    OpenRouter reports per-token pricing and suffixes zero-cost models with
    ``:free``. Local providers are free by definition.
    """
    if str(model_id).endswith(":free"):
        return True

    pricing = entry.get("pricing")
    if isinstance(pricing, dict):
        try:
            prompt_cost = float(pricing.get("prompt", 0) or 0)
            completion_cost = float(pricing.get("completion", 0) or 0)
            return prompt_cost == 0.0 and completion_cost == 0.0
        except (TypeError, ValueError):
            return False

    return False
