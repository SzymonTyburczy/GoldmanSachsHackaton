"""Test helpers shared by gateway tests: demo tokens, config activation, audit outage
and provider stubs."""

import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app import db, policy
from app.adapters.jev import JEV_MODEL
from app.adapters.openai_luna import LUNA_MODEL, SummaryResult, TokenCount
from app.adapters.providers import ProviderSet
from app.contracts import CostStatus, Provider, SemanticCategory, SemanticResult, Usage
from app.policy import ModelsPolicy

TOKENS = {
    "analyst-a": "analyst-a-test-token-0123456789abcdef",
    "reviewer-a": "reviewer-a-test-token-0123456789abcdef",
    "admin": "admin-test-token-0123456789abcdef0123",
}


def config_document(kind: policy.ConfigKind) -> policy.Policy | policy.Feed:
    path = policy.DEFAULT_CONFIG_DIR / policy.CONFIG_FILES[kind]
    return policy.read_config_file(kind, path)


def activate_config(
    db_path: Path, kind: policy.ConfigKind, document: policy.Policy | policy.Feed | None = None
) -> int:
    """Activate ``document`` (default: the file in config/) as the next version."""
    with closing(db.connect(db_path)) as conn:
        current = policy.active_versions(conn)
        stored = policy.activate(
            conn,
            kind,
            document or config_document(kind),
            expected_version=getattr(current, f"{kind}_version"),
            created_by="test",
        )
    return stored.version


def store_task(db_path: Path, principal_id: str, client_id: str = "client-a") -> str:
    """A task written straight to the database, for tests where the API cannot create one
    because no valid policy is active."""
    task_id = str(uuid4())
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at)"
            " VALUES (?, ?, 'demo-agent', ?, ?)",
            (task_id, principal_id, client_id, db.to_db_time(datetime.now(UTC))),
        )
    return task_id


def break_audit(db_path: Path, stage: str) -> None:
    """Make every audit insert for ``stage`` fail, as a full disk or a locked file would."""
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            f"CREATE TRIGGER audit_outage_{stage} BEFORE INSERT ON audit_events"
            f" WHEN NEW.stage = '{stage}' BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
        )


# --------------------------------------------------------------------------------------
# Explicit provider stubs. They stand in for Jev and Luna in offline tests only; a
# result from them says nothing about the real models (tests/live covers those).
# --------------------------------------------------------------------------------------


def stub_usage(provider: Provider, *, input_tokens: int | None, output_tokens: int | None) -> Usage:
    jev = provider is Provider.TYPESAFE
    return Usage(
        provider=provider,
        requested_model=JEV_MODEL if jev else LUNA_MODEL,
        model=JEV_MODEL if jev else LUNA_MODEL,
        provider_response_id=None if jev else "resp_stub",
        input_tokens=input_tokens,
        cached_input_tokens=None if jev else 0,
        output_tokens=output_tokens,
        cost_nusd=None,
        pricing_version=None,
        cost_status=CostStatus.UNKNOWN,
    )


class StubJev:
    """Detector stub with fixed scores; keeps every state it was given."""

    def __init__(self, override: float = 0.05, exfiltration: float = 0.02) -> None:
        self.override = override
        self.exfiltration = exfiltration
        self.error: Exception | None = None
        self.usage = stub_usage(Provider.TYPESAFE, input_tokens=180, output_tokens=2)
        self.during: Callable[[], Awaitable[None]] | None = None
        self.states: list[dict[str, Any]] = []

    async def assess(self, state: Mapping[str, Any]) -> tuple[SemanticResult, Usage]:
        self.states.append(dict(state))
        if self.during is not None:
            await self.during()
        if self.error is not None:
            raise self.error
        result = SemanticResult(
            instruction_override_probability=self.override,
            data_exfiltration_probability=self.exfiltration,
            risk_score=max(self.override, self.exfiltration),
            category=SemanticCategory.BENIGN,
        )
        return result, self.usage


class StubLuna:
    """Token count and summary stub; keeps every input it was given."""

    def __init__(self, text: str = "Fabrikam Logistics is an active client.") -> None:
        self.text = text
        self.input_tokens = 120
        self.count_error: Exception | None = None
        self.summary_error: Exception | None = None
        self.summary_usage = stub_usage(Provider.OPENAI, input_tokens=120, output_tokens=40)
        self.during_summary: Callable[[], Awaitable[None]] | None = None
        self.counted: list[str] = []
        self.summarized: list[str] = []

    async def count_input_tokens(self, *, input: str) -> TokenCount:
        self.counted.append(input)
        if self.count_error is not None:
            raise self.count_error
        usage = stub_usage(Provider.OPENAI, input_tokens=self.input_tokens, output_tokens=None)
        return TokenCount(input_tokens=self.input_tokens, usage=usage)

    async def summarize(self, *, input: str, **options: int) -> SummaryResult:
        self.summarized.append(input)
        if self.during_summary is not None:
            await self.during_summary()
        if self.summary_error is not None:
            raise self.summary_error
        return SummaryResult(text=self.text, usage=self.summary_usage)


class StubProviders:
    """``Providers`` for tests; ``None`` plays a missing API key."""

    def __init__(self) -> None:
        self.jev: StubJev | None = StubJev()
        self.luna: StubLuna | None = StubLuna()

    def connect(self, models: ModelsPolicy) -> ProviderSet:
        return ProviderSet(self.jev, self.luna)
