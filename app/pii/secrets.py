"""Secret masking rules, independent of Presidio.

Presidio does not look for credentials, so known key shapes are replaced here before
Presidio sees the text. The patterns are linear-time regular expressions fixed in code;
the policy chooses only the placeholder. Matches are counted, never stored.
"""

import re

SECRET_ENTITY = "SECRET"  # noqa: S105 (entity type name, not a secret)

SECRET_PATTERNS = (
    # Synthetic ControlProof demo secrets, e.g. in data/documents.
    re.compile(r"cpdemo_[A-Za-z0-9]{16,}"),
    # OpenAI-style API keys (sk-..., sk-proj-...).
    re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    # AWS access key IDs.
    re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
    # GitHub tokens.
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}"),
    # Bearer credentials pasted into text.
    re.compile(r"(?i)(?<![A-Za-z0-9])bearer\s+[A-Za-z0-9\-._~+/]{20,}=*"),
    # PEM private keys.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def mask_secrets(text: str, placeholder: str) -> tuple[str, int]:
    """Replace every known secret shape with ``placeholder``; return the text and count."""
    count = 0
    for pattern in SECRET_PATTERNS:
        text, found = pattern.subn(placeholder, text)
        count += found
    return text, count
