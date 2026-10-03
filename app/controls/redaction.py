"""Redaction before any output.

A2 provides the first step from docs/WSPOLNE_USTALENIA.md, section 2: remove the fields
a role may not see. A4 adds Presidio and the own secret patterns for the remaining text.
"""

from collections.abc import Mapping


def remove_fields(
    fields: Mapping[str, str], allowed: frozenset[str]
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Keep only allowed fields. Returns the kept fields and the sorted removed names."""
    kept = {name: value for name, value in fields.items() if name in allowed}
    removed = tuple(sorted(name for name in fields if name not in allowed))
    return kept, removed
