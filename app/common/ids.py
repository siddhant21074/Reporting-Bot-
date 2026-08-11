"""Unique identifier generation helper functions."""

import uuid


def generate_uuid4() -> str:
    """Generates a standard string representation of a random UUIDv4.

    Returns:
        A 36-character UUID string.
    """
    return str(uuid.uuid4())


def generate_short_id(length: int = 8) -> str:
    """Generates a short random ID by slicing a UUIDv4.

    Args:
        length: Desired length of the sliced ID.

    Returns:
        A string identifier of the requested length.
    """
    return generate_uuid4().replace("-", "")[:length]
