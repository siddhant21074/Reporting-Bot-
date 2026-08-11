"""Meta WhatsApp webhook routes: subscription verification and event intake."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from app.api.dependencies import get_whatsapp_receiver, verify_signature_header
from app.core.config import settings
from app.core.security import verify_token
from app.schemas.webhook import WebhookPayload
from app.services.whatsapp.receiver import WhatsAppReceiver

logger = logging.getLogger("app.api.routes.webhook")
router = APIRouter()

# Meta was originally pointed at bare /webhook; /webhook/whatsapp is the name to
# use now that a second channel exists. Both are served so existing app
# subscriptions keep working without reconfiguration.


@router.get("/webhook", response_class=PlainTextResponse, include_in_schema=False)
@router.get("/webhook/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(default=None, alias="hub.mode"),
    hub_verify_token: str = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Answers Meta's subscription handshake by echoing the challenge.

    Meta sends ``hub.mode=subscribe`` with the verify token configured in the
    app dashboard. The token is compared in constant time and never logged.
    """
    if hub_mode == "subscribe" and verify_token(hub_verify_token, settings.whatsapp.verify_token):
        logger.info(
            "Webhook verification succeeded.",
            extra={"event": "webhook_verification_success"},
        )
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning(
        "Webhook verification failed: mode or verify token did not match.",
        extra={"event": "webhook_verification_failed", "mode": hub_mode},
    )
    return PlainTextResponse(content="Forbidden", status_code=403)


@router.post("/webhook", status_code=200, include_in_schema=False)
@router.post("/webhook/whatsapp", status_code=200)
async def receive_webhook_event(
    request: Request,
    background_tasks: BackgroundTasks,
    receiver: WhatsAppReceiver = Depends(get_whatsapp_receiver),
    _: None = Depends(verify_signature_header),
) -> dict:
    """Accepts a signed Meta webhook event and queues it for processing.

    The signature is verified before anything else runs. Past that point the
    response is always ``200``: Meta retries non-2xx deliveries with backoff and
    eventually disables the subscription, so a payload shape we do not handle is
    logged and dropped rather than rejected.
    """
    raw_body = await request.body()

    try:
        payload = WebhookPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        # Template status updates, account alerts and phone-quality events all
        # arrive on the same subscription with a different shape.
        logger.info(
            "Received a webhook payload that does not match the message schema; ignoring it.",
            extra={"event": "webhook_payload_unhandled", "error_count": exc.error_count()},
        )
        return {"status": "ignored"}
    except Exception as exc:
        logger.error(
            f"Could not decode the webhook body: {exc}",
            extra={"event": "webhook_payload_undecodable"},
        )
        return {"status": "ignored"}

    logger.info(
        "Webhook signature verified; dispatching payload.",
        extra={"event": "webhook_post_validated"},
    )

    try:
        await receiver.receive_webhook(payload, background_tasks)
    except Exception as exc:
        # Never let a processing error turn into a retry storm.
        logger.exception(
            f"Webhook processing raised before dispatch: {exc}",
            extra={"event": "webhook_dispatch_failed"},
        )

    return {"status": "ok"}
