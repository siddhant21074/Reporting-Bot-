"""Shared general utility helper functions."""

from typing import Any


def clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively removes all keys with a value of None from a dictionary.

    Args:
        data: The dictionary to clean.

    Returns:
        A new dictionary without keys that had None values.
    """
    cleaned = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            cleaned[key] = clean_dict(value)
        elif isinstance(value, list):
            cleaned[key] = [
                clean_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned
