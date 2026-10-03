"""Small privacy-neutral JSON report writer used by live checks."""

import json
from pathlib import Path
from typing import Any


def write_json_report(path: Path, report: dict[str, Any]) -> None:
    """Write valid UTF-8 JSON followed by one real line feed."""
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
