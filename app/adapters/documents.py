"""Synthetic document store: a trusted owner catalog and a counted content adapter.

``DocumentCatalog`` holds only metadata (document → client) and never opens content
files, so access control can decide before anything is read. ``DocumentAdapter.read``
is the only code that opens a document; it takes a catalog entry rather than a client
string and counts every call, which tests use to prove a denied request never read.
"""

import threading
from collections import Counter
from pathlib import Path
from typing import Self

from pydantic import ValidationError, model_validator

from app.contracts import FieldName, Identifier, SchemaVersion, StrictModel

CATALOG_FILE = "catalog.json"
CONTENT_DIR = "content"


class CatalogEntry(StrictModel):
    document_id: Identifier
    client_id: Identifier


class _CatalogFile(StrictModel):
    schema_version: SchemaVersion
    documents: tuple[CatalogEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [entry.document_id for entry in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document_id values must be unique")
        return self


class _StoredDocument(StrictModel):
    schema_version: SchemaVersion
    document_id: Identifier
    fields: dict[FieldName, str]


class DocumentReadError(RuntimeError):
    """The document could not be read or validated. The message never has content."""


class DocumentCatalog:
    def __init__(self, entries: tuple[CatalogEntry, ...]) -> None:
        self._entries = {entry.document_id: entry for entry in entries}

    @classmethod
    def load(cls, documents_dir: Path) -> Self:
        """Read and validate the catalog; an invalid catalog stops startup."""
        raw = (documents_dir / CATALOG_FILE).read_bytes()
        return cls(_CatalogFile.model_validate_json(raw).documents)

    def get(self, document_id: str) -> CatalogEntry | None:
        return self._entries.get(document_id)


class DocumentAdapter:
    def __init__(self, documents_dir: Path) -> None:
        self._content_dir = documents_dir / CONTENT_DIR
        self._lock = threading.Lock()
        self.reads: Counter[str] = Counter()  # calls per document_id, including failures

    @property
    def read_count(self) -> int:
        with self._lock:
            return sum(self.reads.values())

    def read(self, entry: CatalogEntry) -> dict[str, str]:
        """Return all stored fields. The caller filters them before any output."""
        with self._lock:
            self.reads[entry.document_id] += 1
        try:
            raw = (self._content_dir / f"{entry.document_id}.json").read_bytes()
            stored = _StoredDocument.model_validate_json(raw)
        except (OSError, ValidationError):
            # Dropped cause: a validation error would carry document content into logs.
            raise DocumentReadError(f"document {entry.document_id} is unreadable") from None
        if stored.document_id != entry.document_id:
            raise DocumentReadError(f"document {entry.document_id} does not match its file")
        return dict(stored.fields)
