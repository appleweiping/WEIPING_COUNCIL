"""Safe JSON-compatible value normalization for provider-influenced data."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 100_000


def sanitize_unicode_scalar(value: str) -> str:
    """Replace isolated UTF-16 surrogate code points with U+FFFD."""
    return "".join(
        "\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character for character in value
    )


def sanitize_json_value(value: Any) -> Any:
    """Copy a JSON-like value while enforcing finite scalars and acyclic bounds."""
    active: set[int] = set()
    item_count = 0

    def visit(item: Any, depth: int) -> Any:
        nonlocal item_count
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON value exceeds maximum nesting depth")
        item_count += 1
        if item_count > MAX_JSON_ITEMS:
            raise ValueError("JSON value exceeds maximum item count")

        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, str):
            return sanitize_unicode_scalar(item)
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("JSON numbers must be finite")
            return item

        identity = id(item)
        if identity in active:
            raise ValueError("cyclic values are not JSON-compatible")
        active.add(identity)
        try:
            if isinstance(item, Mapping):
                result = {}
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError("JSON object keys must be strings")
                    clean_key = sanitize_unicode_scalar(key)
                    if clean_key in result:
                        raise ValueError("Unicode normalization produced a duplicate key")
                    result[clean_key] = visit(child, depth + 1)
                return result
            if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                return [visit(child, depth + 1) for child in item]
        finally:
            active.remove(identity)
        raise ValueError(f"unsupported JSON value type: {type(item).__name__}")

    return visit(value, 0)
