"""AI module exports."""

from app.ai.provider import AIProvider, AIProviderInterface, OpenAIAIProvider
from app.ai.registry import CHAT, PROVIDERS, STT, list_models, providers_for_role
from app.ai.schemas import ExtractedReport, ProjectStatus

__all__ = [
    "AIProvider",
    "AIProviderInterface",
    "OpenAIAIProvider",
    "ExtractedReport",
    "ProjectStatus",
    "PROVIDERS",
    "CHAT",
    "STT",
    "list_models",
    "providers_for_role",
]
