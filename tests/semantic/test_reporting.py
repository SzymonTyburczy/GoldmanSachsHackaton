from __future__ import annotations

import json
from pathlib import Path

from scripts.reporting import write_json_report


def test_json_report_is_valid_and_ends_with_a_real_newline(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    expected = {"mode": "live", "result": "synthetic"}

    write_json_report(report_path, expected)

    raw = report_path.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\\n")
    assert json.loads(raw) == expected
