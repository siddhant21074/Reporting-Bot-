"""Interfaces for WhatsApp client and sender services."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class WhatsAppClientInterface(ABC):
    """Abstract interface for communicating with the Meta WhatsApp Cloud API."""

    @abstractmethod
    async def send_message_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a raw message payload to the Meta WhatsApp messages endpoint."""
        pass


class WhatsAppSenderInterface(ABC):
    """Abstract interface for high-level business message sending operations."""

    @abstractmethod
    async def send_text(self, to: str, text: str, preview_url: bool = False) -> Dict[str, Any]:
        """Sends a text message to a WhatsApp number."""
        pass

    @abstractmethod
    async def send_document(
        self,
        to: str,
        media_id: Optional[str] = None,
        link: Optional[str] = None,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends a document attachment message to a WhatsApp number."""
        pass

    @abstractmethod
    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: list,
        header_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends interactive button reply message to a WhatsApp number."""
        pass
