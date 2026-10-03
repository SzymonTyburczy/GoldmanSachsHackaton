"""Shared data contracts for ControlProof (schema_version 1).

Source of truth for the formats described in docs/WSPOLNE_USTALENIA.md, section 4.
Both people import from here; a change in this file is a contract change and must be
agreed before editing.

Rules applied to every model:
- unknown fields are rejected (``extra="forbid"``),
- models are immutable (``frozen=True``); use ``model_copy(update=...)`` for a new state,
- times are timezone-aware and normalised to UTC,
- missing provider values are ``None``, never a silent zero.

API models (client wire format) and internal models are separate classes.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------------------
# Primitive types
# --------------------------------------------------------------------------------------


def _require_int(value: object) -> object:
    # Literal[1] alone would also accept True and 1.0.
    if type(value) is not int:
        raise ValueError("must be an integer")
    return value


def _reject_bool(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    return value


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


SchemaVersion = Annotated[Literal[1], BeforeValidator(_require_int)]
"""Every persisted or exchanged format carries ``schema_version=1``."""

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
"""Server-side identifier of demo data, e.g. ``analyst-a``, ``client-a``, ``doc-a``.
Never a path, URL or free text."""

FieldName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
"""Name of a document field, e.g. ``company_name``. Never the field value."""

EntityType = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
"""Presidio entity type or own recognizer type, e.g. ``EMAIL_ADDRESS``."""

Token = Annotated[str, StringConstraints(pattern=r"^[\x21-\x7e]{1,128}$")]
"""Printable ASCII token without spaces: model names, provider ids, pricing versions."""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

ConfigVersion = Annotated[int, Strict(), Field(ge=1)]
"""Server-generated, monotonically increasing policy/feed version."""

NonNegativeInt = Annotated[int, Strict(), Field(ge=0)]
PositiveInt = Annotated[int, Strict(), Field(gt=0)]

Probability = Annotated[
    float,
    BeforeValidator(_reject_bool),
    Field(ge=0.0, le=1.0, allow_inf_nan=False),
]

UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REDACT = "REDACT"


class ReasonCode(StrEnum):
    OK = "OK"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"  # authenticated, but the endpoint needs the admin role
    INVALID_INPUT = "INVALID_INPUT"
    TASK_FORBIDDEN = "TASK_FORBIDDEN"
    CLIENT_FORBIDDEN = "CLIENT_FORBIDDEN"
    MODEL_FORBIDDEN = "MODEL_FORBIDDEN"
    TOOL_FORBIDDEN = "TOOL_FORBIDDEN"
    PII_REDACTED = "PII_REDACTED"
    SEMANTIC_RISK = "SEMANTIC_RISK"
    DETECTOR_UNAVAILABLE = "DETECTOR_UNAVAILABLE"
    PII_ENGINE_UNAVAILABLE = "PII_ENGINE_UNAVAILABLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CONCURRENCY_EXCEEDED = "CONCURRENCY_EXCEEDED"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    TOKEN_COUNT_UNAVAILABLE = "TOKEN_COUNT_UNAVAILABLE"  # noqa: S105 (reason code, not a secret)
    ARTIFACT_BLOCKED = "ARTIFACT_BLOCKED"
    INVALID_CONFIG = "INVALID_CONFIG"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    # Returned only by API routes that are still skeletons; never by a control.
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class Stage(StrEnum):
    ADMISSION = "admission"
    PRE_DOCUMENT = "pre_document"
    PRE_DETECTOR = "pre_detector"
    PRE_SUMMARY = "pre_summary"
    POST_OUTPUT = "post_output"
    ARTIFACT = "artifact"


class ExecutionStatus(StrEnum):
    NOT_CALLED = "NOT_CALLED"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ControlId(StrEnum):
    GATEWAY = "gateway"  # authentication, schema, idempotency, request limits
    ACCESS = "access"
    REDACTION = "redaction"
    SEMANTIC = "semantic"
    BUDGET = "budget"
    ARTIFACTS = "artifacts"


class Tool(StrEnum):
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_SUMMARIZE = "documents.summarize"
    ARTIFACTS_ADMIT = "artifacts.admit"


class Role(StrEnum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Provider(StrEnum):
    TYPESAFE = "typesafe"
    OPENAI = "openai"


class SemanticCategory(StrEnum):
    BENIGN = "benign"
    INSTRUCTION_OVERRIDE = "instruction_override"
    DATA_EXFILTRATION = "data_exfiltration"


class CostStatus(StrEnum):
    CALCULATED = "calculated"  # full usage and a verified price table, not an invoice
    ESTIMATED = "estimated"  # conservative amount kept because usage was incomplete
    UNKNOWN = "unknown"


class ReservationPurpose(StrEnum):
    DETECTOR = "detector"
    SUMMARY = "summary"
    FIXTURE = "fixture"


class BudgetUnit(StrEnum):
    NUSD = "nusd"  # 1 USD = 1_000_000_000 nUSD
    TEST_CREDIT = "test_credit"  # offline fixture only; never added to nUSD


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    STARTED = "STARTED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------------------
# Internal models
# --------------------------------------------------------------------------------------


class RequestContext(StrictModel):
    """Built by the server from verified state; never accepted from a client."""

    request_id: UUID
    task_id: UUID
    principal_id: Identifier
    agent_id: Identifier
    role: Role
    client_id: Identifier
    policy_version: ConfigVersion
    feed_version: ConfigVersion
    created_at: UtcDatetime


class ControlResult(StrictModel):
    control_id: ControlId
    decision: Decision
    reason_code: ReasonCode
    stage: Stage
    redacted_fields: tuple[FieldName, ...] = ()


class PiiFinding(StrictModel):
    """Position of a detected fragment in the analysed text, for local masking only.

    Deliberately has no field for the detected value.
    """

    entity_type: EntityType
    start: NonNegativeInt
    end: PositiveInt
    score: Probability

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class SemanticResult(StrictModel):
    """Normalised Jev assessment of a text. Provider metadata goes to ``Usage``."""

    instruction_override_probability: Probability
    data_exfiltration_probability: Probability
    risk_score: Probability
    category: SemanticCategory

    @model_validator(mode="after")
    def _check_aggregate(self) -> Self:
        if self.risk_score != max(
            self.instruction_override_probability, self.data_exfiltration_probability
        ):
            raise ValueError("risk_score must equal the maximum of both probabilities")
        # Whether the score crosses the threshold depends on the policy, but a non-benign
        # category must always point at the dominant question.
        dominant = {
            SemanticCategory.INSTRUCTION_OVERRIDE: self.instruction_override_probability,
            SemanticCategory.DATA_EXFILTRATION: self.data_exfiltration_probability,
        }
        if self.category in dominant and dominant[self.category] != self.risk_score:
            raise ValueError("category must point at the question with the highest probability")
        return self


class Usage(StrictModel):
    """One provider call. All fields are required; unavailable values are ``None``."""

    provider: Provider
    requested_model: Token  # model name from the policy
    model: Token | None  # model name reported by the provider response
    provider_response_id: Token | None
    input_tokens: NonNegativeInt | None
    cached_input_tokens: NonNegativeInt | None
    output_tokens: NonNegativeInt | None
    cost_nusd: NonNegativeInt | None
    pricing_version: Token | None
    cost_status: CostStatus

    @model_validator(mode="after")
    def _check_cost(self) -> Self:
        if self.cost_status is CostStatus.CALCULATED and None in (
            self.input_tokens,
            self.output_tokens,
            self.cost_nusd,
            self.pricing_version,
        ):
            raise ValueError("calculated cost requires full usage, cost_nusd and pricing_version")
        if self.cost_status is CostStatus.ESTIMATED and self.cost_nusd is None:
            raise ValueError("estimated cost requires the conservative cost_nusd")
        if (
            self.cached_input_tokens is not None
            and self.input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        return self


class Reservation(StrictModel):
    reservation_id: UUID
    request_id: UUID
    task_id: UUID
    principal_id: Identifier
    purpose: ReservationPurpose
    unit: BudgetUnit
    amount: PositiveInt
    state: ReservationState
    created_at: UtcDatetime
    pricing_version: Token | None  # None only for test_credit fixtures
    limit_version: ConfigVersion

    @model_validator(mode="after")
    def _check_unit(self) -> Self:
        is_fixture = self.purpose is ReservationPurpose.FIXTURE
        if is_fixture != (self.unit is BudgetUnit.TEST_CREDIT):
            raise ValueError("test_credit is used by fixture reservations and only by them")
        if self.unit is BudgetUnit.NUSD and self.pricing_version is None:
            raise ValueError("nusd reservations require pricing_version")
        return self


class AdapterCalls(StrictModel):
    """Execution status of each adapter within one request."""

    document_read: ExecutionStatus = ExecutionStatus.NOT_CALLED
    token_count: ExecutionStatus = ExecutionStatus.NOT_CALLED
    detector: ExecutionStatus = ExecutionStatus.NOT_CALLED
    summary: ExecutionStatus = ExecutionStatus.NOT_CALLED
    artifact_admit: ExecutionStatus = ExecutionStatus.NOT_CALLED


class AuditEvent(StrictModel):
    """One audit record. Never contains bodies, prompts, documents, tokens or SDK errors."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    event_id: UUID
    request_id: UUID
    task_id: UUID | None
    principal_id: Identifier | None
    agent_id: Identifier | None
    client_id: Identifier | None
    occurred_at: UtcDatetime
    tool: Tool | None
    control_id: ControlId
    decision: Decision
    reason_code: ReasonCode
    stage: Stage
    execution_status: ExecutionStatus
    adapter_calls: AdapterCalls
    usage: tuple[Usage, ...] = ()
    latency_ms: NonNegativeInt | None
    model: Token | None
    policy_version: ConfigVersion | None
    feed_version: ConfigVersion | None
    redacted_fields: tuple[FieldName, ...] = ()
    redacted_entity_counts: dict[EntityType, PositiveInt] = Field(default_factory=dict)
    semantic: SemanticResult | None = None


# --------------------------------------------------------------------------------------
# API models: POST /v1/execute
# --------------------------------------------------------------------------------------

MAX_PROMPT_CHARS = 8000

Prompt = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PROMPT_CHARS)]


class DocumentReadArguments(StrictModel):
    document_id: Identifier


class DocumentSummarizeArguments(StrictModel):
    document_id: Identifier
    prompt: Prompt


class ArtifactAdmitArguments(StrictModel):
    artifact_id: Identifier


class _ExecuteRequestBase(StrictModel):
    schema_version: SchemaVersion
    task_id: UUID


class DocumentReadRequest(_ExecuteRequestBase):
    tool: Literal["documents.read"]
    arguments: DocumentReadArguments


class DocumentSummarizeRequest(_ExecuteRequestBase):
    tool: Literal["documents.summarize"]
    arguments: DocumentSummarizeArguments


class ArtifactAdmitRequest(_ExecuteRequestBase):
    tool: Literal["artifacts.admit"]
    arguments: ArtifactAdmitArguments


ExecuteRequest = Annotated[
    DocumentReadRequest | DocumentSummarizeRequest | ArtifactAdmitRequest,
    Field(discriminator="tool"),
]
"""Body of ``POST /v1/execute``. Parse with ``TypeAdapter(ExecuteRequest)``."""


class DocumentReadOutput(StrictModel):
    kind: Literal["document"] = "document"
    document_id: Identifier
    fields: dict[FieldName, str]  # already filtered and redacted


class SummaryOutput(StrictModel):
    kind: Literal["summary"] = "summary"
    document_id: Identifier
    text: str  # already checked by the output filter


class ArtifactAdmitOutput(StrictModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: Identifier
    sha256: Sha256Hex


ToolOutput = Annotated[
    DocumentReadOutput | SummaryOutput | ArtifactAdmitOutput,
    Field(discriminator="kind"),
]


class ExecuteResponse(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    request_id: UUID
    task_id: UUID
    decision: Decision
    reason_code: ReasonCode
    policy_version: ConfigVersion
    execution_status: ExecutionStatus  # status of the tool requested by the client
    adapter_calls: AdapterCalls
    output: ToolOutput | None
    redacted_fields: tuple[FieldName, ...] = ()
    usage: tuple[Usage, ...] = ()
    audit_event_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def _check_decision(self) -> Self:
        if self.decision is Decision.DENY:
            if self.output is not None:
                raise ValueError("DENY must not carry output")
            if self.reason_code is ReasonCode.OK:
                raise ValueError("DENY requires a reason other than OK")
        else:
            if self.output is None or self.execution_status is not ExecutionStatus.SUCCEEDED:
                raise ValueError("ALLOW/REDACT require a succeeded execution with output")
            if self.reason_code not in (ReasonCode.OK, ReasonCode.PII_REDACTED):
                raise ValueError("ALLOW/REDACT require reason OK or PII_REDACTED")
        return self


# --------------------------------------------------------------------------------------
# API models: other endpoints
# --------------------------------------------------------------------------------------


class CreateTaskRequest(StrictModel):
    """Body of ``POST /v1/tasks``; owner and ID are assigned by the server."""

    schema_version: SchemaVersion
    client_id: Identifier


class TaskResponse(StrictModel):
    """Body returned by ``POST /v1/tasks`` and ``GET /v1/tasks/{task_id}``."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    task_id: UUID
    principal_id: Identifier
    agent_id: Identifier
    client_id: Identifier
    created_at: UtcDatetime


class AuditEventPage(StrictModel):
    """Body of ``GET /admin/events`` and ``GET /v1/tasks/{task_id}/events``, oldest first."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    events: tuple[AuditEvent, ...]
    next_after: PositiveInt | None  # pass as ``after`` for the next page; None on the last


class ErrorDetail(StrictModel):
    """Location and type of a validation error. Never echoes the submitted value."""

    loc: tuple[str | int, ...]
    type: str


class ErrorResponse(StrictModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    request_id: UUID
    reason_code: ReasonCode
    errors: tuple[ErrorDetail, ...] = ()


class HealthResponse(StrictModel):
    """Public process and configuration state. No keys, no paid provider calls."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    policy_version: ConfigVersion | None
    feed_version: ConfigVersion | None
    protected_operations: Literal["enabled", "disabled"]
