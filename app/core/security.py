"""Signature, token and password verification helpers.

Nothing here logs the expected value of a secret. A failed comparison tells you
*that* it failed and which request it was; reproducing it requires the secret,
which lives in configuration, not in the log stream.
"""

import base64
import hashlib
import hmac
import logging

logger = logging.getLogger("app.security")


def verify_whatsapp_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Verifies Meta's ``X-Hub-Signature-256`` header against the raw request body.

    Args:
        payload: The raw request body bytes, exactly as received.
        signature_header: Value of the ``X-Hub-Signature-256`` header.
        secret: The Meta app secret.

    Returns:
        True if the signature is valid.
    """
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header.", extra={"event": "signature_missing"})
        return False

    if not signature_header.startswith("sha256="):
        logger.warning(
            "Signature header is not in the expected 'sha256=' form.",
            extra={"event": "signature_invalid_format"},
        )
        return False

    received = signature_header.split("sha256=", 1)[1].strip()

    try:
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    except Exception as exc:
        logger.error(
            f"Failed to compute HMAC-SHA256: {exc}",
            extra={"event": "signature_computation_error"},
        )
        return False

    if not hmac.compare_digest(received, expected):
        logger.warning(
            "Webhook signature did not match. Request rejected.",
            extra={"event": "signature_mismatch"},
        )
        return False

    logger.debug("Webhook signature verified.", extra={"event": "signature_verified"})
    return True


def verify_token(received: str, expected: str) -> bool:
    """Compares two tokens in constant time.

    Args:
        received: The token supplied by the caller.
        expected: The configured token.

    Returns:
        True if both are non-empty and equal.
    """
    if not received or not expected:
        return False
    return hmac.compare_digest(str(received), str(expected))


# ---------------------------------------------------------------------------
# Admin passwords
# ---------------------------------------------------------------------------


def _prepare(password: str) -> bytes:
    """Normalises a password for bcrypt.

    bcrypt refuses anything over 72 bytes. Pre-hashing with SHA-256 and
    base64-encoding removes that ceiling without truncating -- silently cutting
    a long passphrase would make two different passwords interchangeable.
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """Hashes an admin password for storage in ``ADMIN_PASSWORD_HASH``."""
    import bcrypt

    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Checks a submitted password against a stored hash.

    Returns False rather than raising on a malformed or empty hash, so a
    misconfigured deployment fails closed.
    """
    if not password or not password_hash:
        return False

    import bcrypt

    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except (ValueError, TypeError) as exc:
        logger.error(
            f"Stored admin password hash is not usable: {exc}. "
            "Regenerate it with scripts/make_admin.py.",
            extra={"event": "password_hash_invalid"},
        )
        return False
