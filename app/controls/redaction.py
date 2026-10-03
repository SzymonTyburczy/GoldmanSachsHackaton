"""Redaction before returning data or sending it to providers.

Order for every text that leaves the gateway, to the user or to a provider:

1. keep only the fields allowed for the role (and, towards Jev and OpenAI, also listed
   in ``outbound_fields``); ``email``, ``personal_id`` and ``secret`` never qualify;
2. replace known secret shapes with the own rule (``app.pii.secrets``);
3. let local Presidio find PII in the remaining text and replace it with placeholders.

An unavailable engine raises ``PiiEngineUnavailable``: nothing is returned or sent.
Only field names and counts per entity type are reported, never the removed values.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from app.contracts import Role
from app.controls.semantic import build_jev_state
from app.pii.engine import PiiEngine
from app.pii.secrets import SECRET_ENTITY, mask_secrets
from app.policy import Policy, RedactionPolicy


@dataclass(frozen=True, slots=True)
class Redacted:
    fields: dict[str, str]
    removed: tuple[str, ...]  # sorted names of removed fields
    entity_counts: dict[str, int]  # replaced fragments per entity type

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.entity_counts)


@dataclass(frozen=True, slots=True)
class ProviderInput:
    """Redacted data that may be passed to the Jev and Luna adapters."""

    document: str  # allowed outbound fields as "name: value" lines
    prompt: str | None
    removed: tuple[str, ...]
    entity_counts: dict[str, int]

    def detector_state(self, trusted_task: str) -> dict[str, str]:
        """``state`` for Jev; ``trusted_task`` is a server-written task description."""
        return build_jev_state(
            trusted_task=trusted_task, prompt=self.prompt or "", document=self.document
        )

    def summary_input(self) -> str:
        """Complete ``input`` for Luna's token count and summary."""
        return f"Request:\n{self.prompt or ''}\n\nDocument:\n{self.document}"


def remove_fields(
    fields: Mapping[str, str], allowed: frozenset[str]
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Keep only allowed fields. Returns the kept fields and the sorted removed names."""
    kept = {name: value for name, value in fields.items() if name in allowed}
    removed = tuple(sorted(name for name in fields if name not in allowed))
    return kept, removed


def mask_text(text: str, redaction: RedactionPolicy, engine: PiiEngine) -> tuple[str, Counter]:
    """Apply the secret rule, then Presidio, to the same text."""
    counts: Counter[str] = Counter()
    text, secrets = mask_secrets(text, redaction.secret_placeholder)
    if secrets:
        counts[SECRET_ENTITY] += secrets
    findings = engine.analyze(text, redaction.thresholds)
    if findings:
        text = engine.anonymize(text, findings, redaction.placeholders)
        counts.update(finding.entity_type for finding in findings)
    return text, counts


def redact_fields(
    fields: Mapping[str, str],
    allowed: frozenset[str],
    redaction: RedactionPolicy,
    engine: PiiEngine,
) -> Redacted:
    kept, removed = remove_fields(fields, allowed)
    counts: Counter[str] = Counter()
    masked = {}
    for name, value in kept.items():
        masked[name], found = mask_text(value, redaction, engine)
        counts.update(found)
    return Redacted(masked, removed, dict(sorted(counts.items())))


def prepare_provider_input(
    fields: Mapping[str, str],
    prompt: str | None,
    role: Role,
    policy: Policy,
    engine: PiiEngine,
) -> ProviderInput:
    """The only data the gateway may give to providers, including token counting."""
    document = redact_fields(fields, policy.outbound_fields_for(role), policy.redaction, engine)
    counts = Counter(document.entity_counts)
    clean_prompt = None
    if prompt is not None:
        clean_prompt, found = mask_text(prompt, policy.redaction, engine)
        counts.update(found)
    return ProviderInput(
        document="\n".join(f"{name}: {value}" for name, value in document.fields.items()),
        prompt=clean_prompt,
        removed=document.removed,
        entity_counts=dict(sorted(counts.items())),
    )
