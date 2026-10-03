import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts import Role, Tool
from app.pii.engine import PII_ENTITIES, RECOGNIZERS_VERSION, SUPPORTED_LANGUAGES
from app.policy import CONFIG_FILES, DEFAULT_CONFIG_DIR, Feed, Policy
from app.pricing import DEFAULT_PRICING


def config_dict(kind: str) -> dict[str, Any]:
    return json.loads((DEFAULT_CONFIG_DIR / CONFIG_FILES[kind]).read_text(encoding="utf-8"))


def changed(document: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    """Copy of ``document`` with ``value`` at the dotted ``path`` (``-`` deletes it)."""
    result = copy.deepcopy(document)
    *parents, last = path.split(".")
    target = result
    for part in parents:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if value == "-":
        del target[last]
    else:
        target[last] = value
    return result


def test_shipped_policy_matches_the_shared_agreements() -> None:
    policy = Policy.model_validate(config_dict("policy"))

    assert policy.semantic.block_threshold == 0.8
    assert (policy.models.detector, policy.models.summary) == ("jev-1.13.0", "gpt-6-luna")
    assert policy.fields_for(Role.ANALYST) == {"company_name", "status", "notes"}
    assert policy.fields_for(Role.REVIEWER) == {"company_name", "status", "notes", "review_note"}
    assert policy.fields_for(Role.ADMIN) == policy.fields_for(Role.REVIEWER)
    assert policy.outbound_fields_for(Role.REVIEWER) == {"company_name", "status", "notes"}
    assert Tool.ARTIFACTS_ADMIT not in policy.tools_for(Role.ANALYST)
    assert policy.redaction.languages == SUPPORTED_LANGUAGES
    assert set(policy.redaction.entities) == set(PII_ENTITIES)
    assert policy.redaction.recognizers_version == RECOGNIZERS_VERSION


def test_policy_feeds_the_budget_and_pricing_modules() -> None:
    policy = Policy.model_validate(config_dict("policy"))

    assert policy.pricing.table() == DEFAULT_PRICING
    limits = policy.budget_limits(policy_version=4)
    assert (limits.task_limit, limits.principal_limit, limits.global_limit) == (
        50_000_000,
        200_000_000,
        500_000_000,
    )
    assert (limits.max_requests_per_task, limits.limit_version) == (20, 4)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        # Hard controls cannot be switched off.
        ("controls.access", False),
        ("controls.redaction", False),
        ("controls.budget", False),
        ("controls.access", 1),
        ("controls.semantic", "yes"),
        # Thresholds and limits.
        ("semantic.block_threshold", 1.5),
        ("semantic.block_threshold", True),
        ("semantic.on_error", "allow"),
        ("resources.max_requests_per_task", 0),
        ("budget.task_limit_nusd", "50000000"),
        ("models.summary_timeout_seconds", 600),
        # Only Jev and Luna, each in its own role.
        ("models.allowed", ["jev-1.13.0", "gpt-6-luna", "gpt-4o"]),
        ("models.allowed", ["jev-1.13.0", "jev-1.13.0", "gpt-6-luna"]),
        ("models.allowed", ["jev-1.13.0"]),
        ("models.detector", "gpt-6-luna"),
        ("models.summary_reasoning_effort", "high"),
        # Fields that are always removed, unknown tools and roles.
        ("acl.analyst.fields", ["company_name", "secret"]),
        ("acl.reviewer.fields", ["notes", "notes"]),
        ("acl.admin.tools", ["shell.exec"]),
        ("acl.reviewer", "-"),
        ("acl.auditor", {"tools": [], "fields": []}),
        ("outbound_fields", ["company_name", "email"]),
        ("outbound_fields", ["../notes"]),
        # Redaction keeps all five entities, safe placeholders and known languages.
        ("redaction.entities.PL_PESEL", "-"),
        ("redaction.entities.PERSON", {"threshold": 0.5, "placeholder": "<PERSON>"}),
        ("redaction.entities.EMAIL_ADDRESS.placeholder", "<img src=x onerror=alert(1)>"),
        ("redaction.secret_placeholder", "[removed]"),
        ("redaction.languages", ["de"]),
        ("redaction.languages", []),
        ("redaction.recognizers_version", "controlproof-pii-0"),
        ("redaction.engine", "regex"),
        # Pricing must cover the configured models with integer, non-negative rates.
        ("pricing.openai_model", "gpt-6-luna-mini"),
        ("pricing.openai_output_nusd_per_token", -1),
        ("pricing.openai_output_nusd_per_token", 0.5),
        ("pricing.source_urls", ["http://example.com/prices"]),
        ("pricing.mode", "batch"),
        # Format.
        ("schema_version", 2),
        ("policy_version", 7),
        ("comment", "unknown fields are refused"),
    ],
)
def test_invalid_policy_is_refused(path: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Policy.model_validate(changed(config_dict("policy"), path, value))


def test_shipped_feed_is_valid() -> None:
    assert Feed.model_validate(config_dict("feed")).rules == ()


RULE = {
    "rule_id": "blocked-artifact-1",
    "kind": "sha256",
    "value": "a" * 64,
    "source": "demo-admin",
    "reason": "known unsafe artifact",
    "is_test_fixture": True,
}


@pytest.mark.parametrize(
    "rules",
    [
        [RULE | {"value": "A" * 64}],
        [RULE | {"value": "a" * 63}],
        [RULE | {"kind": "md5"}],
        [RULE | {"reason": "<script>alert(1)</script>"}],
        [RULE, RULE | {"value": "b" * 64}],  # duplicate rule_id
        [RULE, RULE | {"rule_id": "blocked-artifact-2"}],  # duplicate hash
        [RULE | {"rule_id": f"rule-{n}", "value": f"{n:064x}"} for n in range(1001)],
    ],
)
def test_invalid_feed_is_refused(rules: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        Feed.model_validate({"schema_version": 1, "rules": rules})
