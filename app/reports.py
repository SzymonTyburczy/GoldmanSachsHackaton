"""Latest saved test reports for ``GET /admin/test-results``.

Reads the JSON reports that ``make test-live`` (``scripts.evaluate``) and
``make benchmark`` write to ``var/reports``; it never runs a test or calls a provider.
Only file names of the known kinds are read, at most ``MAX_REPORT_BYTES`` each, and only
summary numbers are returned: no samples, prompts or per-case results. Each report keeps
its own time and commit; ``matches_current_commit`` says whether it was produced by the
code that is running, so an old report does not look like a current test.
"""

import json
import re
import shutil
import subprocess
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal

from app.contracts import NonNegativeInt, SchemaVersion, StrictModel, UtcDatetime

ROOT = Path(__file__).resolve().parent.parent
MAX_REPORT_BYTES = 1024 * 1024
REPORT_NAME = re.compile(
    r"^(?P<kind>jev-evaluation|benchmark-offline|benchmark-live)-\d{8}T\d{6}Z\.json$"
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")

ReportKind = Literal["jev-evaluation", "benchmark-offline", "benchmark-live"]


class TestReport(StrictModel):
    kind: ReportKind
    file: str
    mode: Literal["offline", "live"]
    recorded_at: UtcDatetime | None
    git_commit: str | None
    matches_current_commit: bool
    sample_count: NonNegativeInt | None
    passed: bool | None  # None: the report has no pass criterion (offline timings)
    false_positives: NonNegativeInt | None
    false_negatives: NonNegativeInt | None
    errors: NonNegativeInt | None


class TestResults(StrictModel):
    """Body of ``GET /admin/test-results``: the newest readable report of each kind."""

    schema_version: SchemaVersion = 1
    current_commit: str | None
    reports: tuple[TestReport, ...]
    unreadable_files: NonNegativeInt
    offline_suite: Literal["not_recorded"] = "not_recorded"  # make test writes no report


@cache
def current_commit() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        # Fixed command and arguments; the executable is resolved from PATH.
        output = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return output if COMMIT.match(output) else None


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _summary(kind: str, name: str, report: dict[str, Any]) -> TestReport:
    commit = report.get("git_commit")
    commit = commit if isinstance(commit, str) and COMMIT.match(commit) else None
    recorded_at = None
    if isinstance(report.get("recorded_at"), str):
        parsed = datetime.fromisoformat(report["recorded_at"])
        recorded_at = parsed if parsed.tzinfo is not None else None
    fields: dict[str, Any] = {"sample_count": None, "passed": None}
    errors = {"false_positives": None, "false_negatives": None, "errors": None}
    if kind == "jev-evaluation":
        mode = "live"
        fields = {
            "sample_count": _int(report.get("sample_count")),
            "passed": _bool(report.get("passed")),
        }
        errors = {name: _int(report.get(name)) for name in errors}
    elif kind == "benchmark-offline":
        mode = "offline"
        offline = report.get("offline")
        if isinstance(offline, dict):
            fields["sample_count"] = _int(offline.get("iterations"))
    else:
        mode = "live"
        live = report.get("live")
        if isinstance(live, dict):
            fields = {
                "sample_count": _int(live.get("sample_count")),
                "passed": _bool(live.get("passed")),
            }
    return TestReport(
        kind=kind,
        file=name,
        mode=mode,
        recorded_at=recorded_at,
        git_commit=commit,
        matches_current_commit=commit is not None and commit == current_commit(),
        **fields,
        **errors,
    )


def latest(reports_dir: Path) -> TestResults:
    """The newest readable report of each kind; file names sort by their UTC stamp."""
    newest: dict[str, TestReport] = {}
    unreadable = 0
    paths = sorted(reports_dir.glob("*.json"), reverse=True) if reports_dir.is_dir() else []
    for path in paths:
        match = REPORT_NAME.match(path.name)
        if match is None or match["kind"] in newest:
            continue
        try:
            with path.open("rb") as file:
                raw = file.read(MAX_REPORT_BYTES + 1)
            if len(raw) > MAX_REPORT_BYTES:
                raise ValueError("report too large")
            report = json.loads(raw)
            if not isinstance(report, dict):
                raise ValueError("report is not an object")
            newest[match["kind"]] = _summary(match["kind"], path.name, report)
        except (OSError, ValueError):
            unreadable += 1
    return TestResults(
        current_commit=current_commit(),
        reports=tuple(newest[kind] for kind in sorted(newest)),
        unreadable_files=unreadable,
    )
