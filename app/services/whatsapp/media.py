"""Downloads WhatsApp media attachments from the Meta Graph API."""

import logging
import os
import uuid
from typing import Optional

from app.clients.whatsapp_client import WhatsAppClient
from app.core.config import settings
from app.core.constants import META_GRAPH_BASE_URL

logger = logging.getLogger("app.service.whatsapp.media")

# Anything smaller than this is a truncated or error response, not a real file.
MIN_MEDIA_BYTES = 100

_EXTENSION_BY_MIME = (
    (("m4a", "mp4a"), ".m4a"),
    (("ogg", "opus"), ".ogg"),
    (("mpeg", "mp3"), ".mp3"),
    (("wav",), ".wav"),
    (("aac",), ".aac"),
    (("amr",), ".amr"),
    (("png",), ".png"),
    (("webp",), ".webp"),
    (("jpeg", "jpg"), ".jpg"),
    (("pdf",), ".pdf"),
    (("wordprocessingml", "msword"), ".docx"),
    (("mp4",), ".mp4"),
)


class WhatsAppMediaService:
    """Fetches media binaries from Meta and stores them under the media directory."""

    def __init__(self, client: Optional[WhatsAppClient] = None):
        """Initializes the service.

        Args:
            client: WhatsApp client, used for its pooled HTTP connection.
        """
        self.client = client
        self.media_storage_path = settings.app.media_dir
        os.makedirs(self.media_storage_path, exist_ok=True)

    async def download_media(
        self,
        media_id: str,
        mime_type: str = "application/octet-stream",
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """Downloads one attachment.

        Meta requires two calls: one to exchange the media id for a short-lived
        CDN URL, and one to fetch the bytes. Both carry the access token.

        Args:
            media_id: The attachment id from the webhook payload.
            mime_type: MIME type reported by Meta, used to pick a file extension.
            filename: Original filename, if the sender supplied one.

        Returns:
            The local path of the saved file, or ``None`` if the download failed.
            A failed download never leaves a placeholder file behind -- callers
            must treat ``None`` as "the attachment did not arrive".
        """
        access_token = settings.whatsapp.access_token
        if not access_token:
            logger.error(
                "Cannot download media: WHATSAPP_ACCESS_TOKEN is not configured.",
                extra={"event": "media_download_unconfigured"},
            )
            return None

        if not (self.client and getattr(self.client, "http_client", None)):
            logger.error("Cannot download media: no HTTP client is available.")
            return None

        save_path = os.path.join(
            self.media_storage_path,
            f"{media_id}_{uuid.uuid4().hex[:6]}{_pick_extension(mime_type, filename)}",
        )
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            metadata_url = f"{META_GRAPH_BASE_URL}/{settings.whatsapp.api_version}/{media_id}"
            metadata_response = await self.client.http_client.get(metadata_url, headers=headers)
            metadata_response.raise_for_status()

            download_url = metadata_response.json().get("url")
            if not download_url:
                logger.error(
                    f"Meta returned no download URL for media '{media_id}'.",
                    extra={"event": "media_url_missing", "media_id": media_id},
                )
                return None

            download_response = await self.client.http_client.get(
                download_url, headers=headers, follow_redirects=True
            )
            download_response.raise_for_status()
            content = download_response.content

            if len(content) < MIN_MEDIA_BYTES:
                logger.error(
                    f"Media '{media_id}' downloaded as {len(content)} bytes; treating it as failed.",
                    extra={"event": "media_download_too_small", "media_id": media_id},
                )
                return None

            with open(save_path, "wb") as handle:
                handle.write(content)

            logger.info(
                f"Downloaded media '{media_id}' ({len(content)} bytes).",
                extra={
                    "event": "media_download_success",
                    "media_id": media_id,
                    "size_bytes": len(content),
                },
            )
            return save_path

        except Exception as exc:
            logger.error(
                f"Failed to download media '{media_id}': {exc}",
                exc_info=True,
                extra={"event": "media_download_failed", "media_id": media_id},
            )
            # Leave nothing on disk: a placeholder file used to flow downstream
            # as a real photo and as unreadable audio.
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
            return None


def _pick_extension(mime_type: Optional[str], filename: Optional[str]) -> str:
    """Chooses a file extension from the filename, falling back to the MIME type."""
    name = (filename or "").lower()
    if "." in name:
        suffix = name.rsplit(".", 1)[-1]
        if suffix.isalnum() and len(suffix) <= 5:
            return f".{suffix}"

    mime = (mime_type or "").lower()
    for needles, extension in _EXTENSION_BY_MIME:
        if any(needle in mime for needle in needles):
            return extension
    return ".bin"


# Alias kept for existing imports.
WhatsAppMediaDownloader = WhatsAppMediaService
