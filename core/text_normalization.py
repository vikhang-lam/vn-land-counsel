"""Shared deterministic text normalization primitives."""

from __future__ import annotations

import unicodedata


def fold_vietnamese(value: object) -> str:
    """Return a lowercase, accent-insensitive string for contract checks."""

    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    return text.replace("đ", "d")
