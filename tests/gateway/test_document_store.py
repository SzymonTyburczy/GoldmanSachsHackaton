import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.documents import (
    CatalogEntry,
    DocumentAdapter,
    DocumentCatalog,
    DocumentReadError,
)
from app.contracts import Role
from app.settings import DEFAULT_DOCUMENTS_DIR
from tests.gateway.support import config_document

ALWAYS_REMOVED = {"email", "personal_id", "secret"}


def write_catalog(directory: Path, documents: list[dict[str, str]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "documents": documents}
    (directory / "catalog.json").write_text(json.dumps(body), encoding="utf-8")


def test_catalog_assigns_each_document_to_its_client() -> None:
    catalog = DocumentCatalog.load(DEFAULT_DOCUMENTS_DIR)

    assert catalog.get("doc-a") == CatalogEntry(document_id="doc-a", client_id="client-a")
    assert catalog.get("doc-b") == CatalogEntry(document_id="doc-b", client_id="client-b")
    assert catalog.get("doc-zz") is None


def test_catalog_lookup_never_opens_content(tmp_path: Path) -> None:
    write_catalog(tmp_path, [{"document_id": "doc-a", "client_id": "client-a"}])

    # No content directory exists; only the trusted metadata is needed for a decision.
    assert DocumentCatalog.load(tmp_path).get("doc-a") is not None


@pytest.mark.parametrize(
    "documents",
    [
        [{"document_id": "doc-a", "client_id": "client-a"}] * 2,
        [{"document_id": "doc-a", "client_id": "client-a", "path": "/etc/passwd"}],
        [{"document_id": "../doc-a", "client_id": "client-a"}],
    ],
)
def test_invalid_catalog_is_rejected(tmp_path: Path, documents: list[dict[str, str]]) -> None:
    write_catalog(tmp_path, documents)

    with pytest.raises(ValidationError):
        DocumentCatalog.load(tmp_path)


def test_synthetic_documents_hold_the_sensitive_fields_that_must_be_removed() -> None:
    adapter = DocumentAdapter(DEFAULT_DOCUMENTS_DIR)

    for document_id in ("doc-a", "doc-b"):
        entry = DocumentCatalog.load(DEFAULT_DOCUMENTS_DIR).get(document_id)
        assert entry is not None
        fields = adapter.read(entry)
        policy = config_document("policy")
        assert set(fields) >= ALWAYS_REMOVED | policy.fields_for(Role.REVIEWER)
        for role in Role:
            assert not policy.fields_for(role) & ALWAYS_REMOVED


def test_adapter_counts_every_call_including_failures(tmp_path: Path) -> None:
    shutil.copytree(DEFAULT_DOCUMENTS_DIR, tmp_path, dirs_exist_ok=True)
    adapter = DocumentAdapter(tmp_path)
    entry = CatalogEntry(document_id="doc-a", client_id="client-a")

    adapter.read(entry)
    (tmp_path / "content" / "doc-a.json").unlink()
    with pytest.raises(DocumentReadError) as error:
        adapter.read(entry)

    assert adapter.reads == {"doc-a": 2}
    assert adapter.read_count == 2
    assert error.value.__cause__ is None


def test_adapter_rejects_a_file_for_another_document(tmp_path: Path) -> None:
    shutil.copytree(DEFAULT_DOCUMENTS_DIR, tmp_path, dirs_exist_ok=True)
    shutil.copy(tmp_path / "content" / "doc-b.json", tmp_path / "content" / "doc-a.json")

    with pytest.raises(DocumentReadError, match="does not match"):
        DocumentAdapter(tmp_path).read(CatalogEntry(document_id="doc-a", client_id="client-a"))
