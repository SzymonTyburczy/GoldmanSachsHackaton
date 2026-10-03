"""Demo identities and bearer-token authentication.

Identity, role and client scope come only from this server-side directory. A token is
read from the ``Authorization: Bearer`` header and nowhere else; fields such as ``role``
in a request body are rejected by the contracts and never grant anything.

``python -m app.auth .env`` fills empty demo token variables with random values; it
never overwrites a value that is already set and never prints tokens.
"""

import hashlib
import hmac
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from app.api.errors import ApiError
from app.contracts import ReasonCode, Role
from app.settings import Settings

MIN_TOKEN_CHARS = 32
MAX_TOKEN_CHARS = 256
# RFC 6750 b64token: characters that can be sent in a Bearer header unchanged.
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    role: Role
    agent_id: str
    client_ids: frozenset[str]


ANALYST_A = Principal("analyst-a", Role.ANALYST, "demo-agent", frozenset({"client-a"}))
REVIEWER_A = Principal("reviewer-a", Role.REVIEWER, "demo-agent", frozenset({"client-a"}))
ADMIN = Principal("admin", Role.ADMIN, "demo-agent", frozenset({"client-a"}))

# Environment variable, Settings field and the identity its token authenticates.
DEMO_IDENTITIES = (
    ("CONTROLPROOF_TOKEN_ANALYST_A", "token_analyst_a", ANALYST_A),
    ("CONTROLPROOF_TOKEN_REVIEWER_A", "token_reviewer_a", REVIEWER_A),
    ("CONTROLPROOF_TOKEN_ADMIN", "token_admin", ADMIN),
)
DEMO_TOKEN_VARIABLES = tuple(variable for variable, _, _ in DEMO_IDENTITIES)


class InvalidTokenConfigError(ValueError):
    """A configured demo token is too weak or ambiguous; the message never has its value."""


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class TokenDirectory:
    """Maps configured bearer tokens to principals. Keeps only token digests."""

    def __init__(self, tokens: dict[str, tuple[SecretStr | None, Principal]]) -> None:
        entries: list[tuple[bytes, Principal]] = []
        for variable, (secret, principal) in tokens.items():
            if secret is None:
                continue  # identity disabled until its token is set
            token = secret.get_secret_value()
            if not MIN_TOKEN_CHARS <= len(token) <= MAX_TOKEN_CHARS:
                raise InvalidTokenConfigError(
                    f"{variable} must have {MIN_TOKEN_CHARS}-{MAX_TOKEN_CHARS} characters"
                )
            if not TOKEN_PATTERN.fullmatch(token):
                raise InvalidTokenConfigError(f"{variable} has characters outside RFC 6750")
            digest = _digest(token)
            if any(hmac.compare_digest(digest, known) for known, _ in entries):
                raise InvalidTokenConfigError(f"{variable} reuses the token of another identity")
            entries.append((digest, principal))
        self._entries = tuple(entries)

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenDirectory":
        return cls(
            {
                variable: (getattr(settings, field), principal)
                for variable, field, principal in DEMO_IDENTITIES
            }
        )

    def resolve(self, token: str) -> Principal | None:
        digest = _digest(token)
        match = None
        for known, principal in self._entries:  # no early exit: same work for every token
            if hmac.compare_digest(digest, known):
                match = principal
        return match


_bearer = HTTPBearer(
    auto_error=False,
    description="Demo token from .env; never sent as a URL parameter.",
)


def _unauthenticated() -> ApiError:
    return ApiError(401, ReasonCode.AUTH_REQUIRED, headers={"WWW-Authenticate": "Bearer"})


def require_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise _unauthenticated()
    directory: TokenDirectory = request.app.state.tokens
    principal = directory.resolve(credentials.credentials)
    if principal is None:
        raise _unauthenticated()
    return principal


def require_admin(principal: Annotated[Principal, Depends(require_principal)]) -> Principal:
    if principal.role is not Role.ADMIN:
        raise ApiError(403, ReasonCode.ADMIN_REQUIRED)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]


def fill_missing_tokens(env_path: Path) -> list[str]:
    """Write random tokens into empty demo token variables; return the variable names."""
    lines = env_path.read_text(encoding="utf-8").splitlines()
    present: set[str] = set()
    filled: list[str] = []
    for index, line in enumerate(lines):
        name, sep, value = line.partition("=")
        if not sep or name not in DEMO_TOKEN_VARIABLES:
            continue
        present.add(name)
        if not value.strip():
            lines[index] = f"{name}={secrets.token_urlsafe(32)}"
            filled.append(name)
    for name in DEMO_TOKEN_VARIABLES:
        if name not in present:
            lines.append(f"{name}={secrets.token_urlsafe(32)}")
            filled.append(name)
    if filled:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(env_path, 0o600)
    return filled


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    names = fill_missing_tokens(target)
    if names:
        print(f"Generated demo tokens in {target}: {', '.join(names)}")
    else:
        print(f"Demo tokens in {target} are already set.")
