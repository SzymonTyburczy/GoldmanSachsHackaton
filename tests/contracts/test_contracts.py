import math
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts import (
    MAX_PROMPT_CHARS,
    AdapterCalls,
    AuditEvent,
    AuditEventPage,
    BudgetUnit,
    ControlId,
    ControlResult,
    CostStatus,
    Decision,
    DocumentSummarizeRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    PiiFinding,
    Provider,
    ReasonCode,
    RequestContext,
    Reservation,
    ReservationPurpose,
    ReservationState,
    Role,
    SemanticCategory,
    SemanticResult,
    Stage,
    SummaryOutput,
    TaskResponse,
    Usage,
)

execute_request = TypeAdapter(ExecuteRequest)


def summarize_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "task_id": str(uuid4()),
        "tool": "documents.summarize",
        "arguments": {"document_id": "doc-a", "prompt": "Summarize this company."},
    }
    body.update(overrides)
    return body


def usage(**overrides: object) -> Usage:
    fields: dict[str, object] = {
        "provider": Provider.OPENAI,
        "requested_model": "gpt-6-luna",
        "model": "gpt-6-luna",
        "provider_response_id": "resp_123",
        "input_tokens": 120,
        "cached_input_tokens": 0,
        "output_tokens": 300,
        "cost_nusd": 4200,
        "pricing_version": "openai-2026-10-03",
        "cost_status": CostStatus.CALCULATED,
    }
    fields.update(overrides)
    return Usage(**fields)


class TestExecuteRequest:
    def test_each_tool_selects_its_argument_shape(self) -> None:
        parsed = execute_request.validate_python(summarize_body())
        assert isinstance(parsed, DocumentSummarizeRequest)
        read = execute_request.validate_python(
            summarize_body(tool="documents.read", arguments={"document_id": "doc-a"})
        )
        assert read.arguments.document_id == "doc-a"
        admit = execute_request.validate_python(
            summarize_body(tool="artifacts.admit", arguments={"artifact_id": "model-card"})
        )
        assert admit.arguments.artifact_id == "model-card"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"role": "admin"},  # identity is never accepted from the client
            {"model": "gpt-6-luna"},
            {"tool": "shell.exec"},
            {"schema_version": 2},
            {"schema_version": True},
            {"schema_version": "1"},
            {"task_id": "not-a-uuid"},
            {"arguments": {"document_id": "../doc-b", "prompt": "x"}},
            {"arguments": {"document_id": "https://evil.test/doc", "prompt": "x"}},
            {"arguments": {"document_id": "doc-a", "prompt": ""}},
            {"arguments": {"document_id": "doc-a", "prompt": "x", "path": "/etc/passwd"}},
            {"tool": "documents.read"},  # read does not accept a prompt
        ],
    )
    def test_rejects_unknown_or_malformed_input(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            execute_request.validate_python(summarize_body(**overrides))

    def test_prompt_length_limit(self) -> None:
        at_limit = {"document_id": "doc-a", "prompt": "a" * MAX_PROMPT_CHARS}
        execute_request.validate_python(summarize_body(arguments=at_limit))
        over_limit = {"document_id": "doc-a", "prompt": "a" * (MAX_PROMPT_CHARS + 1)}
        with pytest.raises(ValidationError):
            execute_request.validate_python(summarize_body(arguments=over_limit))


class TestRequestContext:
    def fields(self, created_at: datetime) -> dict[str, object]:
        return {
            "request_id": uuid4(),
            "task_id": uuid4(),
            "principal_id": "analyst-a",
            "agent_id": "demo-agent",
            "role": Role.ANALYST,
            "client_id": "client-a",
            "policy_version": 1,
            "feed_version": 1,
            "created_at": created_at,
        }

    def test_normalises_time_to_utc(self) -> None:
        warsaw = timezone(timedelta(hours=2))
        context = RequestContext(**self.fields(datetime(2026, 10, 3, 18, 0, tzinfo=warsaw)))
        assert context.created_at == datetime(2026, 10, 3, 16, 0, tzinfo=UTC)
        assert context.created_at.utcoffset() == timedelta(0)

    def test_rejects_naive_time(self) -> None:
        with pytest.raises(ValidationError):
            RequestContext(**self.fields(datetime(2026, 10, 3, 16, 0)))

    def test_is_immutable(self) -> None:
        context = RequestContext(**self.fields(datetime.now(UTC)))
        with pytest.raises(ValidationError):
            context.role = Role.ADMIN  # type: ignore[misc]


class TestSemanticResult:
    def test_accepts_consistent_result(self) -> None:
        result = SemanticResult(
            instruction_override_probability=0.91,
            data_exfiltration_probability=0.2,
            risk_score=0.91,
            category=SemanticCategory.INSTRUCTION_OVERRIDE,
        )
        assert result.risk_score == 0.91

    @pytest.mark.parametrize(
        ("override", "exfiltration", "risk", "category"),
        [
            (0.9, 0.2, 0.2, SemanticCategory.BENIGN),  # risk_score is not the maximum
            (0.9, 0.2, 0.9, SemanticCategory.DATA_EXFILTRATION),  # wrong dominant question
            (math.nan, 0.2, 0.2, SemanticCategory.BENIGN),
            (1.5, 0.2, 1.5, SemanticCategory.INSTRUCTION_OVERRIDE),
            (-0.1, 0.0, 0.0, SemanticCategory.BENIGN),
            (True, 0.0, 1.0, SemanticCategory.INSTRUCTION_OVERRIDE),
        ],
    )
    def test_rejects_inconsistent_or_invalid_scores(
        self, override: object, exfiltration: float, risk: float, category: SemanticCategory
    ) -> None:
        with pytest.raises(ValidationError):
            SemanticResult(
                instruction_override_probability=override,
                data_exfiltration_probability=exfiltration,
                risk_score=risk,
                category=category,
            )

    def test_tie_allows_either_dominant_category(self) -> None:
        for category in (SemanticCategory.INSTRUCTION_OVERRIDE, SemanticCategory.DATA_EXFILTRATION):
            SemanticResult(
                instruction_override_probability=0.85,
                data_exfiltration_probability=0.85,
                risk_score=0.85,
                category=category,
            )


class TestUsage:
    def test_missing_values_stay_null_not_zero(self) -> None:
        unknown = usage(
            model=None,
            provider_response_id=None,
            input_tokens=None,
            cached_input_tokens=None,
            output_tokens=None,
            cost_nusd=None,
            pricing_version=None,
            cost_status=CostStatus.UNKNOWN,
        )
        dumped = unknown.model_dump(mode="json")
        assert dumped["input_tokens"] is None
        assert dumped["cost_nusd"] is None

    def test_every_field_must_be_given_explicitly(self) -> None:
        with pytest.raises(ValidationError):
            Usage(provider=Provider.TYPESAFE, requested_model="jev-1.13.0", cost_status="unknown")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"output_tokens": None},  # calculated needs full usage
            {"pricing_version": None},
            {"cost_status": CostStatus.ESTIMATED, "cost_nusd": None},
            {"cached_input_tokens": 500},  # more than input_tokens
            {"input_tokens": -1},
            {"cost_nusd": 1.5},
            {"cost_nusd": True},
        ],
    )
    def test_rejects_inconsistent_cost(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            usage(**overrides)


class TestReservation:
    def reservation(self, **overrides: object) -> Reservation:
        fields: dict[str, object] = {
            "reservation_id": uuid4(),
            "request_id": uuid4(),
            "task_id": uuid4(),
            "principal_id": "analyst-a",
            "purpose": ReservationPurpose.DETECTOR,
            "unit": BudgetUnit.NUSD,
            "amount": 1_000_000,
            "state": ReservationState.RESERVED,
            "created_at": datetime.now(UTC),
            "pricing_version": "typesafe-2026-10-03",
            "limit_version": 1,
        }
        fields.update(overrides)
        return Reservation(**fields)

    def test_accepts_detector_and_fixture_reservations(self) -> None:
        self.reservation()
        self.reservation(
            purpose=ReservationPurpose.FIXTURE, unit=BudgetUnit.TEST_CREDIT, pricing_version=None
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"unit": BudgetUnit.TEST_CREDIT},  # test credits only for fixtures
            {"purpose": ReservationPurpose.FIXTURE},  # fixtures never spend nUSD
            {"pricing_version": None},
            {"amount": 0},
            {"amount": True},
            {"amount": 10.0},
        ],
    )
    def test_rejects_invalid_reservation(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            self.reservation(**overrides)


class TestPiiFinding:
    def test_has_no_place_for_the_detected_value(self) -> None:
        with pytest.raises(ValidationError):
            PiiFinding(entity_type="EMAIL_ADDRESS", start=0, end=5, score=0.9, value="a@b.test")

    def test_rejects_empty_span(self) -> None:
        with pytest.raises(ValidationError):
            PiiFinding(entity_type="EMAIL_ADDRESS", start=5, end=5, score=0.9)


class TestExecuteResponse:
    def fields(self, **overrides: object) -> dict[str, object]:
        fields: dict[str, object] = {
            "request_id": uuid4(),
            "task_id": uuid4(),
            "decision": Decision.DENY,
            "reason_code": ReasonCode.CLIENT_FORBIDDEN,
            "policy_version": 1,
            "execution_status": ExecutionStatus.NOT_CALLED,
            "adapter_calls": AdapterCalls(),
            "output": None,
        }
        fields.update(overrides)
        return fields

    def test_deny_without_output(self) -> None:
        response = ExecuteResponse(**self.fields())
        assert response.model_dump(mode="json")["output"] is None

    def test_redacted_success(self) -> None:
        ExecuteResponse(
            **self.fields(
                decision=Decision.REDACT,
                reason_code=ReasonCode.PII_REDACTED,
                execution_status=ExecutionStatus.SUCCEEDED,
                output=SummaryOutput(document_id="doc-a", text="A short summary."),
                redacted_fields=("email",),
            )
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"output": SummaryOutput(document_id="doc-a", text="leak")},  # DENY with output
            {"reason_code": ReasonCode.OK},  # DENY needs a reason
            {"decision": Decision.ALLOW, "reason_code": ReasonCode.OK},  # ALLOW without output
            {
                "decision": Decision.ALLOW,
                "reason_code": ReasonCode.OK,
                "execution_status": ExecutionStatus.FAILED,
                "output": SummaryOutput(document_id="doc-a", text="partial"),
            },
        ],
    )
    def test_rejects_inconsistent_decision(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            ExecuteResponse(**self.fields(**overrides))


def test_control_result_lists_field_names_only() -> None:
    result = ControlResult(
        control_id=ControlId.REDACTION,
        decision=Decision.REDACT,
        reason_code=ReasonCode.PII_REDACTED,
        stage=Stage.PRE_DETECTOR,
        redacted_fields=["email", "secret"],
    )
    assert result.redacted_fields == ("email", "secret")
    with pytest.raises(ValidationError):
        ControlResult(
            control_id=ControlId.REDACTION,
            decision=Decision.REDACT,
            reason_code=ReasonCode.PII_REDACTED,
            stage=Stage.PRE_DETECTOR,
            redacted_fields=["jan.kowalski@example.test"],
        )


def test_audit_event_round_trips_through_json() -> None:
    event = AuditEvent(
        event_id=uuid4(),
        request_id=uuid4(),
        task_id=uuid4(),
        principal_id="analyst-a",
        agent_id="demo-agent",
        client_id="client-a",
        occurred_at=datetime.now(UTC),
        tool="documents.summarize",
        control_id=ControlId.SEMANTIC,
        decision=Decision.DENY,
        reason_code=ReasonCode.SEMANTIC_RISK,
        stage=Stage.PRE_SUMMARY,
        execution_status=ExecutionStatus.NOT_CALLED,
        adapter_calls=AdapterCalls(
            document_read=ExecutionStatus.SUCCEEDED, detector=ExecutionStatus.SUCCEEDED
        ),
        usage=[usage(provider=Provider.TYPESAFE, requested_model="jev-1.13.0")],
        latency_ms=850,
        model="jev-1.13.0",
        policy_version=3,
        feed_version=1,
        redacted_entity_counts={"EMAIL_ADDRESS": 1},
        semantic=SemanticResult(
            instruction_override_probability=0.93,
            data_exfiltration_probability=0.1,
            risk_score=0.93,
            category=SemanticCategory.INSTRUCTION_OVERRIDE,
        ),
    )
    restored = AuditEvent.model_validate_json(event.model_dump_json())
    assert restored == event
    assert restored.model_dump(mode="json")["schema_version"] == 1


class TestTaskResponse:
    def fields(self, **overrides: object) -> dict[str, object]:
        fields: dict[str, object] = {
            "task_id": uuid4(),
            "principal_id": "analyst-a",
            "agent_id": "demo-agent",
            "client_id": "client-a",
            "created_at": datetime(2026, 10, 3, 16, 0, tzinfo=UTC),
        }
        fields.update(overrides)
        return fields

    def test_serialises_with_schema_version_and_utc_time(self) -> None:
        body = TaskResponse(**self.fields()).model_dump(mode="json")

        assert body["schema_version"] == 1
        assert body["created_at"] == "2026-10-03T16:00:00Z"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"created_at": datetime(2026, 10, 3, 16, 0)},
            {"role": "admin"},
            {"principal_id": "Admin User"},
        ],
    )
    def test_rejects_invalid_task(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            TaskResponse(**self.fields(**overrides))


def test_audit_event_page_has_a_positive_cursor_or_none() -> None:
    page = AuditEventPage(events=(), next_after=None)

    assert page.model_dump(mode="json") == {"schema_version": 1, "events": [], "next_after": None}
    for cursor in (0, -1, True, "5"):
        with pytest.raises(ValidationError):
            AuditEventPage(events=(), next_after=cursor)
