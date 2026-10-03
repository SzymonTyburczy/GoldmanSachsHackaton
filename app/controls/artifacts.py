"""Artifact admission: manifest digest, threat feed and a strict JSON schema.

All three checks use the same bytes, read once by ``ArtifactStore.read``: the SHA-256 of
those bytes must equal the manifest digest and must not be listed in the pinned feed, and
only then are the bytes parsed as JSON with a closed schema. Nothing is unpickled,
imported or executed, and a format other than this JSON is refused. No model is called.

The class of threat is CWE-502 (deserialization of untrusted data), e.g. model files in
pickle format that run code when loaded. This check does not reproduce such an attack;
it shows that a blocked or altered artifact is refused before it is used.
"""

import hashlib
from typing import Annotated, Literal

from pydantic import StringConstraints, ValidationError

from app.adapters.artifacts import ManifestEntry
from app.contracts import (
    ControlId,
    ControlResult,
    Decision,
    Identifier,
    ReasonCode,
    SchemaVersion,
    Stage,
    StrictModel,
)
from app.policy import Feed

ArtifactTitle = Annotated[str, StringConstraints(min_length=1, max_length=120)]
ArtifactBody = Annotated[str, StringConstraints(max_length=16_000)]


class ArtifactDocument(StrictModel):
    """The only accepted artifact format: a small, inert JSON document."""

    schema_version: SchemaVersion
    artifact_id: Identifier
    kind: Literal["prompt_template", "model_card"]
    title: ArtifactTitle
    body: ArtifactBody


def _result(decision: Decision, reason_code: ReasonCode) -> ControlResult:
    return ControlResult(
        control_id=ControlId.ARTIFACTS,
        decision=decision,
        reason_code=reason_code,
        stage=Stage.ARTIFACT,
    )


def blocked() -> ControlResult:
    return _result(Decision.DENY, ReasonCode.ARTIFACT_BLOCKED)


def check_bytes(entry: ManifestEntry, data: bytes, feed: Feed) -> tuple[ControlResult, str]:
    """Decide on ``data`` read for ``entry``; returns the result and the bytes' SHA-256."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.sha256:
        return blocked(), digest
    if digest in {rule.value for rule in feed.rules}:
        return blocked(), digest
    try:
        document = ArtifactDocument.model_validate_json(data)
    except ValidationError:
        return blocked(), digest
    if document.artifact_id != entry.artifact_id:
        return blocked(), digest
    return _result(Decision.ALLOW, ReasonCode.OK), digest
