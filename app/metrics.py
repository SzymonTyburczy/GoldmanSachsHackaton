"""Read-only counters for ``GET /admin/metrics``.

Every number comes from the same tables the gateway writes: ``audit_events``,
``requests``, ``budget_accounts`` and ``reservations``. Nothing is estimated here: there
is no security score and no "saved money". Amounts are integer nUSD; ``test_credit``
fixtures are never mixed in. Limits are those of the active policy.
"""

import sqlite3
from typing import Literal

from app.contracts import (
    ControlId,
    NonNegativeInt,
    ReasonCode,
    SchemaVersion,
    Stage,
    StrictModel,
    UtcDatetime,
    utc_now,
)
from app.policy import Feed, Policy, StoredConfig


class ControlState(StrictModel):
    control_id: Literal["access", "redaction", "semantic", "budget", "artifacts"]
    enabled: bool


class BudgetScope(StrictModel):
    scope: Literal["global", "principal"]
    scope_id: str
    limit_nusd: NonNegativeInt
    spent_nusd: NonNegativeInt
    reserved_nusd: NonNegativeInt
    remaining_nusd: int  # may be negative after an admin lowered the limit


class PurposeCost(StrictModel):
    """Provider cost per reservation purpose: settled amounts and amounts still held."""

    purpose: Literal["detector", "summary"]
    settled_nusd: NonNegativeInt
    held_nusd: NonNegativeInt  # RESERVED, STARTED or UNKNOWN: not released, not settled
    reservations: NonNegativeInt


class StageLatency(StrictModel):
    control_id: ControlId
    stage: Stage
    samples: NonNegativeInt
    p50_ms: NonNegativeInt
    max_ms: NonNegativeInt


class AdminMetrics(StrictModel):
    schema_version: SchemaVersion = 1
    generated_at: UtcDatetime
    policy_version: int | None
    feed_version: int | None
    feed_rules: NonNegativeInt | None
    controls: tuple[ControlState, ...]
    requests_seen: NonNegativeInt  # distinct request IDs in the audit log
    outcomes: dict[str, NonNegativeInt]  # stored responses by decision, plus unresolved
    denials: dict[ReasonCode, NonNegativeInt]  # DENY events by reason code
    budget: tuple[BudgetScope, ...]
    cost: tuple[PurposeCost, ...]
    reservations_by_state: dict[str, NonNegativeInt]
    latency: tuple[StageLatency, ...]


def _controls(policy: Policy | None) -> tuple[ControlState, ...]:
    if policy is None:
        return ()
    return tuple(
        ControlState(control_id=name, enabled=enabled)
        for name, enabled in policy.controls.model_dump().items()
    )


def _budget(conn: sqlite3.Connection, policy: Policy | None) -> tuple[BudgetScope, ...]:
    if policy is None:
        return ()
    rows = conn.execute(
        "SELECT scope, scope_id, spent, reserved FROM budget_accounts"
        " WHERE unit = 'nusd' AND scope IN ('global', 'principal')"
        " ORDER BY scope = 'principal', scope_id"
    ).fetchall()
    seen = {(row["scope"], row["scope_id"]): row for row in rows}
    if ("global", "global") not in seen:
        rows = [{"scope": "global", "scope_id": "global", "spent": 0, "reserved": 0}, *rows]
    limits = {
        "global": policy.budget.global_limit_nusd,
        "principal": policy.budget.principal_limit_nusd,
    }
    return tuple(
        BudgetScope(
            scope=row["scope"],
            scope_id=row["scope_id"],
            limit_nusd=limits[row["scope"]],
            spent_nusd=row["spent"],
            reserved_nusd=row["reserved"],
            remaining_nusd=limits[row["scope"]] - row["spent"] - row["reserved"],
        )
        for row in rows
    )


def _cost(conn: sqlite3.Connection) -> tuple[PurposeCost, ...]:
    rows = conn.execute(
        "SELECT purpose,"
        " coalesce(sum(CASE WHEN state = 'SETTLED' THEN settled_amount END), 0) AS settled,"
        " coalesce(sum(CASE WHEN state IN ('RESERVED', 'STARTED', 'UNKNOWN')"
        "   THEN amount END), 0) AS held,"
        " count(*) AS n"
        " FROM reservations WHERE unit = 'nusd' GROUP BY purpose"
    ).fetchall()
    found = {row["purpose"]: row for row in rows}
    return tuple(
        PurposeCost(
            purpose=purpose,
            settled_nusd=found[purpose]["settled"] if purpose in found else 0,
            held_nusd=found[purpose]["held"] if purpose in found else 0,
            reservations=found[purpose]["n"] if purpose in found else 0,
        )
        for purpose in ("detector", "summary")
    )


def _latency(conn: sqlite3.Connection) -> tuple[StageLatency, ...]:
    rows = conn.execute(
        "SELECT control_id, stage, json_extract(event_json, '$.latency_ms') AS ms"
        " FROM audit_events WHERE json_extract(event_json, '$.latency_ms') IS NOT NULL"
    ).fetchall()
    groups: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        groups.setdefault((row["control_id"], row["stage"]), []).append(row["ms"])
    result = []
    for (control_id, stage), values in sorted(groups.items()):
        values.sort()
        result.append(
            StageLatency(
                control_id=control_id,
                stage=stage,
                samples=len(values),
                p50_ms=values[(len(values) - 1) // 2],
                max_ms=values[-1],
            )
        )
    return tuple(result)


def collect(
    conn: sqlite3.Connection, policy: StoredConfig | None, feed: StoredConfig | None
) -> AdminMetrics:
    active = policy.document if policy is not None else None
    active = active if isinstance(active, Policy) else None
    rules = feed.document.rules if feed is not None and isinstance(feed.document, Feed) else None
    outcomes = {
        row["outcome"]: row["n"]
        for row in conn.execute(
            "SELECT CASE WHEN state = 'COMPLETED'"
            " THEN json_extract(response_body, '$.decision') ELSE state END AS outcome,"
            " count(*) AS n FROM requests GROUP BY outcome"
        )
    }
    denials = {
        row["reason_code"]: row["n"]
        for row in conn.execute(
            "SELECT reason_code, count(*) AS n FROM audit_events"
            " WHERE decision = 'DENY' GROUP BY reason_code ORDER BY n DESC, reason_code"
        )
    }
    states = {
        row["state"]: row["n"]
        for row in conn.execute(
            "SELECT state, count(*) AS n FROM reservations WHERE unit = 'nusd' GROUP BY state"
        )
    }
    seen = conn.execute("SELECT count(DISTINCT request_id) FROM audit_events").fetchone()[0]
    return AdminMetrics(
        generated_at=utc_now(),
        policy_version=None if policy is None else policy.version,
        feed_version=None if feed is None else feed.version,
        feed_rules=None if rules is None else len(rules),
        controls=_controls(active),
        requests_seen=seen,
        outcomes=outcomes,
        denials=denials,
        budget=_budget(conn, active),
        cost=_cost(conn),
        reservations_by_state=states,
        latency=_latency(conn),
    )
