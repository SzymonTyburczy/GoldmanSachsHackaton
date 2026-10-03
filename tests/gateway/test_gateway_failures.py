import shutil
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.settings import DEFAULT_DOCUMENTS_DIR, Settings
from tests.gateway.support import activate_config


@pytest.fixture
def documents_dir(tmp_path: Path) -> Path:
    path = tmp_path / "documents"
    shutil.copytree(DEFAULT_DOCUMENTS_DIR, path)
    return path


@pytest.fixture
def settings(settings: Settings, documents_dir: Path) -> Settings:
    return settings.model_copy(update={"documents_dir": documents_dir})


@pytest.mark.parametrize(
    "content",
    [
        '{"truncated": "Fabrikam',  # not JSON
        '{"schema_version": 1, "document_id": "doc-b", "fields": {"notes": "Fabrikam"}}',
    ],
)
@pytest.mark.usefixtures("active_config")
def test_unreadable_document_fails_closed(
    client: TestClient,
    documents_dir: Path,
    new_task: Callable[..., str],
    execute: Callable[..., httpx.Response],
    content: str,
) -> None:
    (documents_dir / "content" / "doc-a.json").write_text(content, encoding="utf-8")

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    assert response.status_code == 200
    body = response.json()
    assert (body["decision"], body["reason_code"]) == ("DENY", "UPSTREAM_FAILED")
    assert body["execution_status"] == "FAILED"
    assert body["adapter_calls"]["document_read"] == "FAILED"
    assert body["output"] is None
    assert "Fabrikam" not in response.text
    assert client.app.state.documents.read_count == 1  # the attempt is still counted


@pytest.mark.parametrize("active", [[], ["policy"], ["feed"]])
def test_protected_operations_need_an_active_policy_and_feed(
    client: TestClient,
    db_path: Path,
    new_task: Callable[..., str],
    execute: Callable[..., httpx.Response],
    active: list[str],
) -> None:
    for kind in active:
        activate_config(db_path, kind, 1)

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    assert response.status_code == 503
    assert response.json()["reason_code"] == "INVALID_CONFIG"
    assert client.app.state.documents.read_count == 0
