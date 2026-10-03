"""Process settings read from environment variables (see .env.example).

Secrets are kept as ``SecretStr`` so they do not appear in reprs or logs.
Empty values count as missing.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

DEFAULT_DB_PATH = Path("var/controlproof.sqlite3")
# Synthetic demo documents and their trusted owner catalog, shipped with the code.
DEFAULT_DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    db_path: Path = DEFAULT_DB_PATH
    documents_dir: Path = DEFAULT_DOCUMENTS_DIR
    # Demo identities (A2): random bearer tokens mapped to identities on the server.
    token_analyst_a: SecretStr | None = None
    token_reviewer_a: SecretStr | None = None
    token_admin: SecretStr | None = None
    # Provider keys (B1); used only by backend adapters.
    openai_api_key: SecretStr | None = None
    typesafe_api_key: SecretStr | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        def value(name: str) -> str | None:
            raw = environ.get(name, "").strip()
            return raw or None

        db_path = value("CONTROLPROOF_DB_PATH")
        return cls(
            db_path=Path(db_path) if db_path else DEFAULT_DB_PATH,
            token_analyst_a=value("CONTROLPROOF_TOKEN_ANALYST_A"),
            token_reviewer_a=value("CONTROLPROOF_TOKEN_REVIEWER_A"),
            token_admin=value("CONTROLPROOF_TOKEN_ADMIN"),
            openai_api_key=value("OPENAI_API_KEY"),
            typesafe_api_key=value("TYPESAFE_API_KEY"),
        )
