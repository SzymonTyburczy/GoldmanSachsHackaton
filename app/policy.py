"""Versioned policy and artifact feed (docs/WSPOLNE_USTALENIA.md, section 6).

The files in ``config/`` only seed or import a configuration. After activation the
version stored in SQLite is the source of truth and survives a restart. Activation
validates the complete document, assigns the next version and moves the active pointer
in one transaction. A stale ``expected_version`` changes nothing, and an invalid document
never reaches the database, so the last valid version stays active. Each request pins
the versions active when it starts. Without an active policy and feed, protected
operations are refused.

``python -m app.policy seed`` imports the files for kinds without an active version
(``make setup``). ``python -m app.policy reload`` imports both files through the same
validation as ``PUT /admin/policy`` (``make reload-config``).
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app import db
from app.adapters.jev import JEV_MODEL
from app.adapters.openai_luna import LUNA_MODEL
from app.budget import BudgetLimits
from app.contracts import (
    ConfigVersion,
    EntityType,
    FieldName,
    Identifier,
    NonNegativeInt,
    PositiveInt,
    Probability,
    Provider,
    Role,
    SchemaVersion,
    Sha256Hex,
    StrictModel,
    Token,
    Tool,
    UtcDatetime,
    utc_now,
)
from app.pii.engine import PII_ENTITIES, RECOGNIZERS_VERSION, SUPPORTED_LANGUAGES
from app.pricing import PricingTable
from app.settings import Settings

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_FILES = {"policy": "policy.json", "feed": "threat-feed.json"}

# The only models the adapters can call (AGENTS.md: no models beyond Jev and Luna).
SUPPORTED_MODELS = {JEV_MODEL: Provider.TYPESAFE, LUNA_MODEL: Provider.OPENAI}
# Removed in every profile; a policy cannot show them to a role or send them out.
ALWAYS_REMOVED_FIELDS = frozenset({"email", "personal_id", "secret"})
MAX_FEED_RULES = 1000

ConfigKind = Literal["policy", "feed"]
Language = Literal[*SUPPORTED_LANGUAGES]


def _unique[T](values: tuple[T, ...]) -> tuple[T, ...]:
    if len(set(values)) != len(values):
        raise ValueError("values must be unique")
    return values


def _not_always_removed(fields: tuple[str, ...]) -> tuple[str, ...]:
    if ALWAYS_REMOVED_FIELDS.intersection(fields):
        raise ValueError("email, personal_id and secret are always removed")
    return fields


Fields = Annotated[
    tuple[FieldName, ...], AfterValidator(_unique), AfterValidator(_not_always_removed)
]
Placeholder = Annotated[str, StringConstraints(pattern=r"^<[A-Z][A-Z0-9_]{0,63}>$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[\x21-\x7e]{1,200}$")]
FeedText = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._:/()-]{0,119}$")]


def _switched_on(value: bool) -> bool:
    if value is not True:
        raise ValueError("this control cannot be switched off")
    return value


HardControl = Annotated[StrictBool, AfterValidator(_switched_on)]
SummaryTimeout = Annotated[int, Field(strict=True, ge=1, le=120)]
DetectorTimeout = Annotated[int, Field(strict=True, ge=1, le=60)]


# --------------------------------------------------------------------------------------
# Policy document
# --------------------------------------------------------------------------------------


class ControlsPolicy(StrictModel):
    """Access, redaction, budget and the semantic detector cannot be switched off.

    Without the detector no document leaves the gateway, so switching it off would only
    look like a setting. ``artifacts=false`` refuses ``artifacts.admit`` altogether
    (``TOOL_FORBIDDEN``); it never admits an artifact without the manifest and feed check.
    """

    access: HardControl
    redaction: HardControl
    budget: HardControl
    semantic: HardControl
    artifacts: StrictBool


class SemanticPolicy(StrictModel):
    block_threshold: Probability  # DENY when risk_score >= block_threshold
    on_error: Literal["deny"]


class ModelsPolicy(StrictModel):
    allowed: Annotated[tuple[Token, ...], AfterValidator(_unique), Field(min_length=1)]
    detector: Token
    summary: Token
    summary_max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=16384)]
    summary_reasoning_effort: Literal["low"]  # the Luna adapter sends effort=low
    summary_timeout_seconds: SummaryTimeout
    detector_reserved_input_tokens: PositiveInt
    detector_timeout_seconds: DetectorTimeout

    @model_validator(mode="after")
    def _check_models(self) -> Self:
        unknown = [model for model in self.allowed if model not in SUPPORTED_MODELS]
        if unknown:
            raise ValueError("allowed models must be supported by the adapters")
        if self.detector not in self.allowed or self.summary not in self.allowed:
            raise ValueError("detector and summary models must be allowed")
        if SUPPORTED_MODELS[self.detector] is not Provider.TYPESAFE:
            raise ValueError("the detector must be a TypeSafe model")
        if SUPPORTED_MODELS[self.summary] is not Provider.OPENAI:
            raise ValueError("the summary model must be an OpenAI model")
        return self


class ResourcesPolicy(StrictModel):
    max_summary_input_tokens: PositiveInt
    max_detector_state_chars: PositiveInt
    max_requests_per_task: PositiveInt
    max_provider_calls_per_task: PositiveInt
    max_concurrency_per_principal: PositiveInt
    max_tasks_per_principal: PositiveInt
    max_requests_per_minute_per_principal: PositiveInt


class BudgetPolicy(StrictModel):
    task_limit_nusd: PositiveInt
    principal_limit_nusd: PositiveInt
    global_limit_nusd: PositiveInt


class RoleAccess(StrictModel):
    tools: Annotated[tuple[Tool, ...], AfterValidator(_unique)]
    fields: Fields


class AclPolicy(StrictModel):
    analyst: RoleAccess
    reviewer: RoleAccess
    admin: RoleAccess

    def for_role(self, role: Role) -> RoleAccess:
        return getattr(self, role.value)


class EntityRule(StrictModel):
    threshold: Probability
    placeholder: Placeholder


class RedactionPolicy(StrictModel):
    engine: Literal["presidio"]
    recognizers_version: Literal[RECOGNIZERS_VERSION]
    languages: Annotated[tuple[Language, ...], AfterValidator(_unique), Field(min_length=1)]
    entities: dict[EntityType, EntityRule]
    secret_placeholder: Placeholder

    @model_validator(mode="after")
    def _check_entities(self) -> Self:
        if set(self.entities) != set(PII_ENTITIES):
            raise ValueError(f"entities must be exactly {', '.join(PII_ENTITIES)}")
        return self

    @property
    def thresholds(self) -> dict[str, float]:
        return {entity: rule.threshold for entity, rule in self.entities.items()}

    @property
    def placeholders(self) -> dict[str, str]:
        return {entity: rule.placeholder for entity, rule in self.entities.items()}


class PricingPolicy(StrictModel):
    """Verified provider rates in integer nUSD per token; see ``app.pricing``.

    The rates that size each reservation are positive: a zero amount cannot be reserved.
    """

    version: Token
    verified_on: date
    mode: Literal["standard"]
    source_urls: Annotated[tuple[HttpsUrl, ...], Field(min_length=1)]
    typesafe_model: Token
    openai_model: Token
    typesafe_input_nusd_per_token: PositiveInt
    openai_input_nusd_per_token: NonNegativeInt
    openai_cached_input_nusd_per_token: NonNegativeInt
    openai_cache_write_nusd_per_token: NonNegativeInt
    openai_output_nusd_per_token: PositiveInt
    openai_long_context_threshold: PositiveInt
    openai_long_input_nusd_per_token: NonNegativeInt
    openai_long_cached_input_nusd_per_token: NonNegativeInt
    openai_long_cache_write_nusd_per_token: NonNegativeInt
    openai_long_output_nusd_per_token: NonNegativeInt

    def table(self) -> PricingTable:
        rates = self.model_dump(exclude={"verified_on", "mode", "source_urls"})
        return PricingTable(**rates)


class Policy(StrictModel):
    schema_version: SchemaVersion
    controls: ControlsPolicy
    semantic: SemanticPolicy
    models: ModelsPolicy
    resources: ResourcesPolicy
    budget: BudgetPolicy
    acl: AclPolicy
    outbound_fields: Fields  # fields that may reach Jev and OpenAI, before redaction
    redaction: RedactionPolicy
    pricing: PricingPolicy

    @model_validator(mode="after")
    def _check_pricing_models(self) -> Self:
        if (self.pricing.typesafe_model, self.pricing.openai_model) != (
            self.models.detector,
            self.models.summary,
        ):
            raise ValueError("pricing must cover the configured detector and summary models")
        return self

    def tools_for(self, role: Role) -> frozenset[Tool]:
        return frozenset(self.acl.for_role(role).tools)

    def fields_for(self, role: Role) -> frozenset[str]:
        return frozenset(self.acl.for_role(role).fields)

    def outbound_fields_for(self, role: Role) -> frozenset[str]:
        """Fields that may leave for a provider: within the role's scope and outbound."""
        return self.fields_for(role) & frozenset(self.outbound_fields)

    def budget_limits(self, policy_version: int) -> BudgetLimits:
        return BudgetLimits(
            task_limit=self.budget.task_limit_nusd,
            principal_limit=self.budget.principal_limit_nusd,
            global_limit=self.budget.global_limit_nusd,
            max_requests_per_task=self.resources.max_requests_per_task,
            max_provider_calls_per_task=self.resources.max_provider_calls_per_task,
            max_concurrency_per_principal=self.resources.max_concurrency_per_principal,
            max_tasks_per_principal=self.resources.max_tasks_per_principal,
            limit_version=policy_version,
        )


# --------------------------------------------------------------------------------------
# Feed document (rules are checked by artifacts.admit, app.controls.artifacts)
# --------------------------------------------------------------------------------------


class FeedRule(StrictModel):
    rule_id: Identifier
    kind: Literal["sha256"]
    value: Sha256Hex
    source: FeedText
    reason: FeedText
    is_test_fixture: StrictBool


class Feed(StrictModel):
    schema_version: SchemaVersion
    rules: Annotated[tuple[FeedRule, ...], Field(max_length=MAX_FEED_RULES)]

    @model_validator(mode="after")
    def _check_rules(self) -> Self:
        _unique(tuple(rule.rule_id for rule in self.rules))
        _unique(tuple(rule.value for rule in self.rules))
        return self


DOCUMENT_MODELS: dict[str, type[Policy] | type[Feed]] = {"policy": Policy, "feed": Feed}


# --------------------------------------------------------------------------------------
# API models: GET and PUT /admin/policy and /admin/feed
# --------------------------------------------------------------------------------------


class PolicyUpdate(StrictModel):
    """Body of ``PUT /admin/policy``: the complete policy and the version it replaces."""

    schema_version: SchemaVersion
    expected_version: ConfigVersion | None  # None only while no policy is active
    policy: Policy


class ActivePolicy(StrictModel):
    """Body of ``GET`` and ``PUT /admin/policy``."""

    schema_version: SchemaVersion = 1
    policy_version: ConfigVersion
    sha256: Sha256Hex
    created_at: UtcDatetime
    created_by: Identifier
    policy: Policy


class FeedUpdate(StrictModel):
    """Body of ``PUT /admin/feed``: the complete feed and the version it replaces."""

    schema_version: SchemaVersion
    expected_version: ConfigVersion | None  # None only while no feed is active
    feed: Feed


class ActiveFeed(StrictModel):
    """Body of ``GET`` and ``PUT /admin/feed``."""

    schema_version: SchemaVersion = 1
    feed_version: ConfigVersion
    sha256: Sha256Hex
    created_at: UtcDatetime
    created_by: Identifier
    feed: Feed


# --------------------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------------------


class VersionConflictError(Exception):
    """``expected_version`` is not the active version; nothing was changed."""


class StoredConfigError(RuntimeError):
    """A stored version is missing or no longer passes validation."""


@dataclass(frozen=True, slots=True)
class StoredConfig:
    kind: ConfigKind
    version: int
    document: Policy | Feed
    sha256: str
    created_at: datetime
    created_by: str


def canonical_json(document: Policy | Feed) -> str:
    return json.dumps(
        document.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _active_version(conn: sqlite3.Connection, kind: ConfigKind) -> int | None:
    row = conn.execute("SELECT version FROM active_config WHERE kind = ?", (kind,)).fetchone()
    return None if row is None else row["version"]


def activate(
    conn: sqlite3.Connection,
    kind: ConfigKind,
    document: Policy | Feed,
    *,
    expected_version: int | None,
    created_by: str,
) -> StoredConfig:
    """Store ``document`` as the next version and make it active, or change nothing."""
    if not isinstance(document, DOCUMENT_MODELS[kind]):
        raise TypeError(f"expected a {kind} document")
    body = canonical_json(document)
    digest = _digest(body)
    now = utc_now()
    with db.transaction(conn):
        if _active_version(conn, kind) != expected_version:
            raise VersionConflictError(kind)
        version = conn.execute(
            "SELECT coalesce(max(version), 0) + 1 FROM config_versions WHERE kind = ?", (kind,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO config_versions (kind, version, body, sha256, created_at, created_by)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, version, body, digest, db.to_db_time(now), created_by),
        )
        conn.execute(
            "INSERT INTO active_config (kind, version, activated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (kind) DO UPDATE"
            " SET version = excluded.version, activated_at = excluded.activated_at",
            (kind, version, db.to_db_time(now)),
        )
    _documents[(kind, digest)] = document
    return StoredConfig(kind, version, document, digest, now, created_by)


# Stored versions never change, so a validated document can be reused by its digest.
_documents: dict[tuple[str, str], Policy | Feed] = {}


def load(conn: sqlite3.Connection, kind: ConfigKind, version: int) -> StoredConfig:
    """A stored version, validated again with the current code."""
    row = conn.execute(
        "SELECT body, sha256, created_at, created_by FROM config_versions"
        " WHERE kind = ? AND version = ?",
        (kind, version),
    ).fetchone()
    if row is None:
        raise StoredConfigError(f"{kind} version {version} is not stored")
    digest = _digest(row["body"])
    if digest != row["sha256"]:
        raise StoredConfigError(f"{kind} version {version} does not match its digest")
    document = _documents.get((kind, digest))
    if document is None:
        try:
            document = DOCUMENT_MODELS[kind].model_validate_json(row["body"])
        except ValidationError:
            raise StoredConfigError(f"{kind} version {version} is no longer valid") from None
        _documents[(kind, digest)] = document
    return StoredConfig(
        kind,
        version,
        document,
        digest,
        datetime.fromisoformat(row["created_at"]),
        row["created_by"],
    )


def load_active(conn: sqlite3.Connection, kind: ConfigKind) -> StoredConfig | None:
    version = _active_version(conn, kind)
    return None if version is None else load(conn, kind, version)


@dataclass(frozen=True, slots=True)
class ActiveVersions:
    policy_version: int | None
    feed_version: int | None

    @property
    def ready(self) -> bool:
        return self.policy_version is not None and self.feed_version is not None


def active_versions(conn: sqlite3.Connection) -> ActiveVersions:
    return ActiveVersions(
        policy_version=_active_version(conn, "policy"),
        feed_version=_active_version(conn, "feed"),
    )


# --------------------------------------------------------------------------------------
# Import from config/ (make setup, make reload-config)
# --------------------------------------------------------------------------------------


class ConfigFileError(Exception):
    def __init__(self, path: Path, problems: list[str]) -> None:
        super().__init__(f"{path}: invalid")
        self.path = path
        self.problems = problems


def read_config_file(kind: ConfigKind, path: Path) -> Policy | Feed:
    try:
        return DOCUMENT_MODELS[kind].model_validate_json(path.read_bytes())
    except OSError as exc:
        raise ConfigFileError(path, [type(exc).__name__]) from None
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in error['loc']) or '(document)'}: {error['msg']}"
            for error in exc.errors()
        ]
        raise ConfigFileError(path, problems) from None


def import_files(db_path: Path, config_dir: Path, *, only_missing: bool) -> list[str]:
    """Validate both files first, then activate each changed one. Returns a report."""
    documents = {
        kind: read_config_file(kind, config_dir / filename)
        for kind, filename in CONFIG_FILES.items()
    }
    created_by = "cli-seed" if only_missing else "cli-reload"
    report = []
    with closing(db.connect(db_path)) as conn:
        for kind, document in documents.items():
            current = _active_version(conn, kind)
            if current is not None:
                row = conn.execute(
                    "SELECT sha256 FROM config_versions WHERE kind = ? AND version = ?",
                    (kind, current),
                ).fetchone()
                if only_missing or row["sha256"] == _digest(canonical_json(document)):
                    report.append(f"{kind}: version {current} stays active")
                    continue
            stored = activate(conn, kind, document, expected_version=current, created_by=created_by)
            report.append(f"{kind}: version {stored.version} activated")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.policy")
    parser.add_argument("command", choices=["seed", "reload"])
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    db_path = Settings.from_env().db_path
    db.init_db(db_path)
    try:
        report = import_files(db_path, args.config_dir, only_missing=args.command == "seed")
    except ConfigFileError as exc:
        print(f"{exc.path}: not activated; the active configuration is unchanged", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    except VersionConflictError:
        print("configuration changed during import; nothing more was activated", file=sys.stderr)
        return 1
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
