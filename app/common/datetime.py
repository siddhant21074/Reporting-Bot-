"""Utility functions for date and time operations."""

from datetime import datetime, timezone


def get_utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime.

    Returns:
        A datetime object set to UTC.
    """
    return datetime.now(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Formats a datetime object into a standard ISO-8601 string.

    Args:
        dt: The datetime object to format.

    Returns:
        ISO-8601 formatted string.
    """
    return dt.isoformat()


def timestamp_to_utc_datetime(ts: float) -> datetime:
    """Converts a Unix epoch timestamp to a timezone-aware UTC datetime object.

    Args:
        ts: A float/int unix timestamp.

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(ts, timezone.utc)
