"""Synthetic artifact store: a trusted manifest and a counted, size-bounded byte reader.

``ArtifactManifest`` holds the expected SHA-256 of every known artifact and never opens
content files, so an unknown artifact is refused before anything is read.
``ArtifactStore.read`` is the only code that opens an artifact. It returns raw bytes,
at most ``MAX_ARTIFACT_BYTES``; it never parses, unpickles or executes them. The caller
hashes, checks and parses those same bytes (``app.controls.artifacts``).
"""

import threading
from collections import Counter
from pathlib import Path
from typing import Self

from pydantic import model_validator

from app.contracts import Identifier, SchemaVersion, Sha256Hex, StrictModel

MANIFEST_FILE = "manifest.json"
CONTENT_DIR = "content"
CONTENT_SUFFIX = ".artifact"
MAX_ARTIFACT_BYTES = 64 * 1024


class ManifestEntry(StrictModel):
    artifact_id: Identifier
    sha256: Sha256Hex  # digest the publisher declared for these bytes


class _ManifestFile(StrictModel):
    schema_version: SchemaVersion
    artifacts: tuple[ManifestEntry, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [entry.artifact_id for entry in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact_id values must be unique")
        return self


class ArtifactReadError(RuntimeError):
    """The artifact could not be read. The message never has content."""


class ArtifactTooLarge(ArtifactReadError):
    """The artifact has more than ``MAX_ARTIFACT_BYTES``; the rest was not read."""


class ArtifactManifest:
    def __init__(self, entries: tuple[ManifestEntry, ...]) -> None:
        self._entries = {entry.artifact_id: entry for entry in entries}

    @classmethod
    def load(cls, artifacts_dir: Path) -> Self:
        """Read and validate the manifest; an invalid manifest stops startup."""
        raw = (artifacts_dir / MANIFEST_FILE).read_bytes()
        return cls(_ManifestFile.model_validate_json(raw).artifacts)

    def get(self, artifact_id: str) -> ManifestEntry | None:
        return self._entries.get(artifact_id)


class ArtifactStore:
    def __init__(self, artifacts_dir: Path) -> None:
        self._content_dir = artifacts_dir / CONTENT_DIR
        self._lock = threading.Lock()
        self.reads: Counter[str] = Counter()  # calls per artifact_id, including failures

    @property
    def read_count(self) -> int:
        with self._lock:
            return sum(self.reads.values())

    def read(self, entry: ManifestEntry) -> bytes:
        """Return the stored bytes, refusing more than ``MAX_ARTIFACT_BYTES``."""
        with self._lock:
            self.reads[entry.artifact_id] += 1
        path = self._content_dir / f"{entry.artifact_id}{CONTENT_SUFFIX}"
        try:
            with path.open("rb") as file:
                data = file.read(MAX_ARTIFACT_BYTES + 1)
        except OSError:
            raise ArtifactReadError(f"artifact {entry.artifact_id} is unreadable") from None
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ArtifactTooLarge(f"artifact {entry.artifact_id} exceeds the size limit")
        return data
