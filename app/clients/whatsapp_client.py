"""Concrete implementation of the WhatsApp client calling Meta Cloud API."""

import os
import logging
from typing import Any, Dict
import httpx

from app.core.config import settings
from app.core.constants import META_GRAPH_BASE_URL
from app.core.exceptions import ConfigurationError, MetaAPIError
from app.services.interfaces.whatsapp import WhatsAppClientInterface

logger = logging.getLogger("app.client.whatsapp")


class WhatsAppClient(WhatsAppClientInterface):
    """Low-level infrastructure client handling HTTP requests to the Meta Graph API."""

    def __init__(self, http_client: httpx.AsyncClient):
        """Initializes the WhatsApp client.

        Args:
            http_client: Configured async HTTP client pooled during application lifespan.
        """
        self.http_client = http_client

    async def send_message_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        whatsapp_settings = settings.whatsapp

        # Validate configuration status
        if not whatsapp_settings.access_token or not whatsapp_settings.phone_number_id:
            logger.error(
                "WhatsApp API authentication keys are unconfigured.",
                extra={"event": "whatsapp_client_unconfigured"}
            )
            raise ConfigurationError(
                "WhatsApp Access Token or Phone Number ID configuration is missing in the environment."
            )

        url = f"{META_GRAPH_BASE_URL}/{whatsapp_settings.api_version}/{whatsapp_settings.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {whatsapp_settings.access_token}",
            "Content-Type": "application/json",
        }

        logger.info(
            f"Sending outbound request to Meta WhatsApp API ({whatsapp_settings.api_version})",
            extra={
                "event": "meta_api_request_sent",
                "to": payload.get("to"),
                "message_type": payload.get("type"),
            }
        )

        try:
            response = await self.http_client.post(url, json=payload, headers=headers)

            logger.info(
                f"Received Meta API response status={response.status_code}",
                extra={
                    "event": "meta_api_response_received",
                    "status_code": response.status_code,
                    "response": response.text,
                }
            )

            # Check if Meta returned an error status code
            if response.is_error:
                error_msg = response.text
                try:
                    error_json = response.json()
                    if "error" in error_json:
                        error_msg = error_json["error"].get("message", error_msg)
                except Exception:
                    pass

                raise MetaAPIError(
                    message=f"Meta API returned error: {error_msg}",
                    status_code=response.status_code,
                    details=response.text
                )

            return response.json()

        except httpx.HTTPError as exc:
            logger.error(
                f"Meta API request transport failure: {exc}",
                extra={"event": "meta_api_transport_failure", "error": str(exc)}
            )
            raise MetaAPIError(
                message=f"Failed to connect to Meta Graph API: {str(exc)}",
                status_code=502,
                details=str(exc)
            )

    async def upload_media(
        self, file_path: str, mime_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ) -> str:
        """Uploads a local media file to Meta Graph API and returns the media_id.

        Args:
            file_path: Absolute local path to the file.
            mime_type: MIME type string.

        Returns:
            The uploaded media_id string.
        """
        whatsapp_settings = settings.whatsapp
        if not whatsapp_settings.access_token or not whatsapp_settings.phone_number_id:
            raise ConfigurationError("WhatsApp credentials missing in environment.")

        url = f"{META_GRAPH_BASE_URL}/{whatsapp_settings.api_version}/{whatsapp_settings.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {whatsapp_settings.access_token}"}

        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        files = {"file": (filename, file_bytes, mime_type)}
        data = {"messaging_product": "whatsapp", "type": mime_type}

        logger.info(f"Uploading file '{filename}' ({len(file_bytes)} bytes) to Meta Media endpoint...")

        try:
            response = await self.http_client.post(url, headers=headers, data=data, files=files)
            if response.is_error:
                raise MetaAPIError(message=f"Media upload failed: {response.text}", status_code=response.status_code)

            res_json = response.json()
            media_id = res_json.get("id")
            logger.info(f"Successfully uploaded media. Assigned media_id='{media_id}'")
            return media_id
        except Exception as exc:
            logger.error(f"Failed to upload media to Meta API: {exc}")
            raise MetaAPIError(message=f"Media upload transport failure: {exc}", status_code=502)
