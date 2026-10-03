"""Measure local controls or a bounded, budgeted live Jev→Luna provider pipeline.

The live profile uses only the repository's synthetic evaluation cases and the configured
B3/B4 reservations. Reports omit prompts, documents, summaries and secret values.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app import db
from app.adapters.documents import CatalogEntry
from app.adapters.jev import JevAdapter
from app.adapters.openai_luna import OpenAILunaAdapter
from app.auth import ANALYST_A
from app.budget import BudgetLimits, balances, mark_started, reserve, settle
from app.contracts import (
    BudgetUnit,
    RequestContext,
    ReservationPurpose,
    Role,
    SemanticCategory,
    utc_now,
)
from app.controls import access
from app.controls.redaction import remove_fields
from app.controls.semantic import build_jev_state, evaluate
from app.pricing import DEFAULT_PRICING
from app.provider_calls import assess_with_budget, summarize_with_budget
from app.settings import Settings
from scripts.evaluate import TRUSTED_TASK, USER_PROMPT, _git_commit, _percentile
from scripts.evaluation_cases import EVALUATION_CASES

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "var" / "reports"


class _BudgetedJevEvaluator:
    def __init__(
        self,
        *,
        db_path: Path,
        context: RequestContext,
        adapter: JevAdapter,
        limits: BudgetLimits,
    ) -> None:
        self._db_path = db_path
        self._context = context
        self._adapter = adapter
        self._limits = limits

    async def assess(self, state: Mapping[str, Any]):
        result, usage, _ = await assess_with_budget(
            db_path=self._db_path,
            context=self._context,
            adapter=self._adapter,
            state=state,
            limits=self._limits,
            pricing=DEFAULT_PRICING,
        )
        return result, usage


def _percentile_summary(milliseconds: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(milliseconds),
        "p50_ms": _percentile(milliseconds, 50),
        "p95_ms": _percentile(milliseconds, 95),
    }


def _write_report(report: dict[str, Any], *, mode: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORT_DIR / f"benchmark-{mode}-{stamp}.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report_path


def _prepare_task(db_path: Path, *, principal_id: str, agent_id: str, client_id: str) -> UUID:
    task_id = uuid4()
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(task_id), principal_id, agent_id, client_id, utc_now().isoformat()),
        )
    return task_id


def _insert_request(
    db_path: Path, *, request_id: UUID, task_id: UUID, principal_id: str, state: str
) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO requests
               (request_id, principal_id, idempotency_key, request_sha256, task_id, tool,
                state, created_at)
               VALUES (?, ?, ?, ?, ?, 'documents.read', ?, ?)""",
            (
                str(request_id),
                principal_id,
                str(uuid4()),
                hashlib.sha256(str(request_id).encode()).hexdigest(),
                str(task_id),
                state,
                utc_now().isoformat(),
            ),
        )


def _set_request_state(db_path: Path, request_id: UUID, state: str) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute("UPDATE requests SET state = ? WHERE request_id = ?", (state, str(request_id)))


def _local_benchmark(iterations: int) -> dict[str, Any]:
    """Measure currently implemented A2 access/field rules and B3 SQLite fixture costs."""
    context = RequestContext(
        request_id=uuid4(),
        task_id=uuid4(),
        principal_id=ANALYST_A.principal_id,
        agent_id=ANALYST_A.agent_id,
        role=ANALYST_A.role,
        client_id="client-a",
        policy_version=1,
        feed_version=1,
        created_at=utc_now(),
    )
    allowed_document = CatalogEntry(document_id="doc-a", client_id="client-a")
    blocked_document = CatalogEntry(document_id="doc-b", client_id="client-b")
    fields = {
        "company_name": "Acme Example",
        "status": "active",
        "notes": "synthetic benchmark record",
        "email": "synthetic@example.invalid",
        "secret": "SYNTHETIC-NOT-A-REAL-SECRET",
    }
    allowed_fields = access.readable_fields(Role.ANALYST)
    access_allow_times: list[float] = []
    access_deny_times: list[float] = []
    field_filter_times: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter_ns()
        allowed = access.check_document(context, allowed_document)
        access_allow_times.append((time.perf_counter_ns() - start) / 1_000_000)
        if allowed.decision.value != "ALLOW":
            raise RuntimeError("expected local access allow result")

        start = time.perf_counter_ns()
        denied = access.check_document(context, blocked_document)
        access_deny_times.append((time.perf_counter_ns() - start) / 1_000_000)
        if denied.decision.value != "DENY":
            raise RuntimeError("expected local access deny result")

        start = time.perf_counter_ns()
        kept, removed = remove_fields(fields, allowed_fields)
        field_filter_times.append((time.perf_counter_ns() - start) / 1_000_000)
        if "email" in kept or "secret" in kept or not removed:
            raise RuntimeError("local field filter failed its synthetic control check")

    with tempfile.TemporaryDirectory(prefix="controlproof-benchmark-") as directory:
        db_path = Path(directory) / "benchmark.sqlite3"
        db.init_db(db_path)
        task_id = _prepare_task(
            db_path,
            principal_id=ANALYST_A.principal_id,
            agent_id=ANALYST_A.agent_id,
            client_id="client-a",
        )
        reservation_contexts: list[RequestContext] = []
        for _ in range(iterations):
            request_id = uuid4()
            _insert_request(
                db_path,
                request_id=request_id,
                task_id=task_id,
                principal_id=ANALYST_A.principal_id,
                state="COMPLETED",
            )
            reservation_contexts.append(
                RequestContext(
                    request_id=request_id,
                    task_id=task_id,
                    principal_id=ANALYST_A.principal_id,
                    agent_id=ANALYST_A.agent_id,
                    role=ANALYST_A.role,
                    client_id="client-a",
                    policy_version=1,
                    feed_version=1,
                    created_at=utc_now(),
                )
            )
        limits = BudgetLimits(
            task_limit=iterations,
            principal_limit=iterations,
            global_limit=iterations,
            max_requests_per_task=iterations,
            max_provider_calls_per_task=iterations,
            max_concurrency_per_principal=20,
            max_tasks_per_principal=10,
            limit_version=1,
        )
        budget_times: list[float] = []
        for context in reservation_contexts:
            _set_request_state(db_path, context.request_id, "IN_PROGRESS")
            start = time.perf_counter_ns()
            reservation = reserve(
                db_path,
                context,
                ReservationPurpose.FIXTURE,
                BudgetUnit.TEST_CREDIT,
                1,
                limits,
            )
            mark_started(db_path, reservation.reservation_id)
            settle(db_path, reservation.reservation_id, 1)
            _set_request_state(db_path, context.request_id, "COMPLETED")
            budget_times.append((time.perf_counter_ns() - start) / 1_000_000)
        final_balance = balances(
            db_path,
            unit=BudgetUnit.TEST_CREDIT,
            task_id=task_id,
            principal_id=ANALYST_A.principal_id,
        )
        if final_balance["global"] != {"spent": iterations, "reserved": 0}:
            raise RuntimeError("offline budget benchmark did not settle every fixture credit")

    return {
        "profile": "offline_local_components",
        "iterations": iterations,
        "access_allow": _percentile_summary(access_allow_times),
        "access_deny": _percentile_summary(access_deny_times),
        "field_filter": _percentile_summary(field_filter_times),
        "sqlite_fixture_reserve_start_settle": _percentile_summary(budget_times),
        "fixture_credits_spent": iterations,
        "pii_engine": "not measured: Presidio gateway integration is not yet implemented",
        "scope_note": (
            "Local component timings only; excludes HTTP gateway, Presidio analysis, "
            "provider calls, "
            "and audit. Fixture credits are not USD and do not measure model inference."
        ),
    }


def _limits() -> BudgetLimits:
    return BudgetLimits(
        task_limit=50_000_000,
        principal_limit=200_000_000,
        global_limit=500_000_000,
        max_requests_per_task=20,
        max_provider_calls_per_task=40,
        max_concurrency_per_principal=2,
        max_tasks_per_principal=10,
        limit_version=1,
    )


async def _live_benchmark(threshold: float) -> dict[str, Any]:
    settings = Settings.from_env()
    if settings.typesafe_api_key is None or settings.openai_api_key is None:
        raise RuntimeError("both provider keys are required for the live benchmark")

    with tempfile.TemporaryDirectory(prefix="controlproof-live-benchmark-") as directory:
        db_path = Path(directory) / "benchmark.sqlite3"
        db.init_db(db_path)
        principal_id = ANALYST_A.principal_id
        task_id = _prepare_task(
            db_path,
            principal_id=principal_id,
            agent_id=ANALYST_A.agent_id,
            client_id="client-a",
        )
        limits = _limits()
        jev = JevAdapter(settings.typesafe_api_key.get_secret_value())
        luna = OpenAILunaAdapter(settings.openai_api_key.get_secret_value(), max_output_tokens=2048)
        jev_ms: list[float] = []
        luna_ms: list[float] = []
        hybrid_ms: list[float] = []
        total_cost_nusd = 0
        cases: list[dict[str, Any]] = []
        false_positives = 0
        false_negatives = 0

        for case in EVALUATION_CASES:
            request_id = uuid4()
            _insert_request(
                db_path,
                request_id=request_id,
                task_id=task_id,
                principal_id=principal_id,
                state="IN_PROGRESS",
            )
            context = RequestContext(
                request_id=request_id,
                task_id=task_id,
                principal_id=principal_id,
                agent_id=ANALYST_A.agent_id,
                role=ANALYST_A.role,
                client_id="client-a",
                policy_version=1,
                feed_version=1,
                created_at=utc_now(),
            )
            state = build_jev_state(
                trusted_task=TRUSTED_TASK,
                prompt=USER_PROMPT,
                document=case.content,
            )
            evaluator = _BudgetedJevEvaluator(
                db_path=db_path, context=context, adapter=jev, limits=limits
            )
            sample_start = time.perf_counter()
            detector_start = time.perf_counter()
            result, jev_usage = await evaluate(evaluator, state=state, block_threshold=threshold)
            detector_elapsed = (time.perf_counter() - detector_start) * 1000
            jev_ms.append(detector_elapsed)
            total_cost_nusd += jev_usage.cost_nusd or 0
            blocked = result.category is not SemanticCategory.BENIGN
            luna_usage: list[dict[str, Any]] = []
            if not blocked:
                # All records are synthetic; no PII is present in this benchmark fixture.
                summary_input = f"{USER_PROMPT}\nSynthetic record: {case.content}"
                luna_start = time.perf_counter()
                _, summary, count_usage, summary_usage, _, _ = await summarize_with_budget(
                    db_path=db_path,
                    context=context,
                    adapter=luna,
                    input=summary_input,
                    limits=limits,
                    pricing=DEFAULT_PRICING,
                    max_input_tokens=8192,
                    max_output_tokens=2048,
                )
                elapsed = (time.perf_counter() - luna_start) * 1000
                luna_ms.append(elapsed)
                total_cost_nusd += summary_usage.cost_nusd or 0
                luna_usage = [
                    {
                        "stage": "token_count",
                        "input_tokens": count_usage.input_tokens,
                        "output_tokens": count_usage.output_tokens,
                        "cost_nusd": count_usage.cost_nusd,
                    },
                    {
                        "stage": "summary",
                        "input_tokens": summary_usage.input_tokens,
                        "output_tokens": summary_usage.output_tokens,
                        "cost_nusd": summary_usage.cost_nusd,
                        "cost_status": summary_usage.cost_status.value,
                        "summary_nonempty": bool(summary.text.strip()),
                    },
                ]
            sample_elapsed = (time.perf_counter() - sample_start) * 1000
            hybrid_ms.append(sample_elapsed)
            false_positives += int(not case.malicious and blocked)
            false_negatives += int(case.malicious and not blocked)
            cases.append(
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "expected_malicious": case.malicious,
                    "blocked": blocked,
                    "risk_score": result.risk_score,
                    "jev_input_tokens": jev_usage.input_tokens,
                    "jev_output_tokens": jev_usage.output_tokens,
                    "jev_cost_nusd": jev_usage.cost_nusd,
                    "jev_latency_ms": round(detector_elapsed, 3),
                    "luna_usage": luna_usage,
                    "hybrid_latency_ms": round(sample_elapsed, 3),
                }
            )
            _set_request_state(db_path, request_id, "COMPLETED")

        final_balance = balances(
            db_path, unit=BudgetUnit.NUSD, task_id=task_id, principal_id=principal_id
        )

    return {
        "profile": "budgeted_hybrid_provider_pipeline",
        "mode": "live",
        "threshold": threshold,
        "sample_count": len(cases),
        "model_versions": {"jev_requested": "jev-1.13.0", "luna_requested": "gpt-6-luna"},
        "jev": _percentile_summary(jev_ms),
        "luna_token_count_plus_summary": _percentile_summary(luna_ms),
        "provider_chain_per_sample": _percentile_summary(hybrid_ms),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "estimated_total_cost_nusd": total_cost_nusd,
        "final_global_balance_nusd": final_balance["global"],
        "cases": cases,
        "scope_note": (
            "Synthetic provider pipeline with B3/B4 reservations. Not an end-to-end gateway "
            "benchmark: access, Presidio, active policy/feed and audit are not included."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--live", action="store_true", help="also run 12 billable synthetic cases")
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()
    if args.iterations <= 0:
        parser.error("--iterations must be positive")
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between 0 and 1")

    started = datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": 1,
        "recorded_at": started.isoformat(),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "threshold": args.threshold,
        "held_out_case_count": len(EVALUATION_CASES),
        "offline": _local_benchmark(args.iterations),
        "live": None,
    }
    if args.live:
        try:
            report["live"] = asyncio.run(_live_benchmark(args.threshold))
        except Exception as exc:
            report["live"] = {"passed": False, "error_type": type(exc).__name__}
            report_path = _write_report(report, mode="live")
            print(
                f"Live benchmark failed ({type(exc).__name__}); report: {report_path}",
                file=sys.stderr,
            )
            return 1

    mode = "live" if args.live else "offline"
    report_path = _write_report(report, mode=mode)
    offline = report["offline"]
    print(
        f"Offline benchmark: {args.iterations} iterations; report: {report_path.relative_to(ROOT)}"
    )
    for name, result in offline.items():
        if isinstance(result, dict) and "p50_ms" in result:
            print(f"  {name}: p50={result['p50_ms']} ms, p95={result['p95_ms']} ms")
    if args.live:
        live = report["live"]
        print(f"Live hybrid provider profile: {live['sample_count']} synthetic cases")
        print(f"  Jev p50/p95: {live['jev']['p50_ms']}/{live['jev']['p95_ms']} ms")
        print(
            "  Luna count+summary p50/p95: "
            f"{live['luna_token_count_plus_summary']['p50_ms']}/"
            f"{live['luna_token_count_plus_summary']['p95_ms']} ms"
        )
        print(
            "  per-sample provider chain p50/p95: "
            f"{live['provider_chain_per_sample']['p50_ms']}/"
            f"{live['provider_chain_per_sample']['p95_ms']} ms"
        )
        print(
            f"  FP/FN={live['false_positives']}/{live['false_negatives']}; "
            f"estimated cost={live['estimated_total_cost_nusd']} nUSD"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
