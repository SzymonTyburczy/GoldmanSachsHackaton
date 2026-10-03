"""Local Presidio Analyzer and Anonymizer (docs/WSPOLNE_USTALENIA.md, section 2).

Everything runs on this machine. The spaCy pipelines come from the lockfile; a missing
pipeline is an error here, because Presidio would otherwise try to download it during a
request. The email recognizer validates the domain locally instead of with tldextract,
which may fetch the public suffix list and rejects reserved domains such as ``.example``.

Each text is analysed once per configured language with the same recognizers. Results
below the per-entity threshold are dropped. Overlapping results, also across languages,
are merged into one span covering all of them, labelled with the entity of the highest
score (ties: the order of ``PII_ENTITIES``). The Anonymizer then replaces each span in the
same text with its placeholder. Findings carry positions and scores, never values.

``python -m app.pii.engine`` loads the pipelines and runs a synthetic check (make setup).
"""

import logging
import threading
from collections.abc import Iterable, Mapping

import spacy.util
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    PlPeselRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.contracts import PiiFinding

# Version of the recognizer set below together with app.pii.secrets; stored in the policy.
RECOGNIZERS_VERSION = "controlproof-pii-1"
PII_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "PL_PESEL")
SPACY_MODELS = {"en": "en_core_web_sm", "pl": "pl_core_news_sm"}
SUPPORTED_LANGUAGES = tuple(SPACY_MODELS)
PHONE_REGIONS = ("PL", "US", "GB", "DE", "FR")

# Presidio logs fragments of the analysed text (e.g. context words) at DEBUG level.
# Raw content must not reach any log, so its loggers are switched off; failures surface
# here as PiiEngineUnavailable with no detail.
for _name in ("presidio-analyzer", "presidio-anonymizer"):
    logging.getLogger(_name).disabled = True


class PiiEngineUnavailable(RuntimeError):
    """The local engine could not be built or failed; the caller must deny."""


class LocalEmailRecognizer(EmailRecognizer):
    """Presidio's email pattern with an offline domain check."""

    def validate_result(self, pattern_text: str) -> bool:
        top_level = pattern_text.rpartition("@")[2].rpartition(".")[2]
        return len(top_level) >= 2 and top_level.isalpha()


def _registry(languages: Iterable[str]) -> RecognizerRegistry:
    languages = list(languages)
    registry = RecognizerRegistry(supported_languages=languages)
    for language in languages:
        registry.add_recognizer(LocalEmailRecognizer(supported_language=language))
        registry.add_recognizer(
            PhoneRecognizer(supported_language=language, supported_regions=PHONE_REGIONS)
        )
        registry.add_recognizer(IbanRecognizer(supported_language=language))
        registry.add_recognizer(CreditCardRecognizer(supported_language=language))
        registry.add_recognizer(PlPeselRecognizer(supported_language=language))
    return registry


class PiiEngine:
    def __init__(self, languages: tuple[str, ...]) -> None:
        for language in languages:
            model = SPACY_MODELS.get(language)
            if model is None or not spacy.util.is_package(model):
                raise PiiEngineUnavailable(f"spaCy pipeline for {language!r} is not installed")
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": language, "model_name": SPACY_MODELS[language]}
                    for language in languages
                ],
            }
        ).create_engine()
        self.languages = languages
        self._analyzer = AnalyzerEngine(
            registry=_registry(languages),
            nlp_engine=nlp_engine,
            supported_languages=list(languages),
        )
        self._anonymizer = AnonymizerEngine()
        self._lock = threading.Lock()

    def analyze(self, text: str, thresholds: Mapping[str, float]) -> list[PiiFinding]:
        """Merged findings for the entities in ``thresholds``, ordered by position."""
        entities = [entity for entity in PII_ENTITIES if entity in thresholds]
        if not text or not entities:
            return []
        try:
            with self._lock:
                results = [
                    result
                    for language in self.languages
                    for result in self._analyzer.analyze(
                        text=text, language=language, entities=entities
                    )
                    if result.score >= thresholds[result.entity_type]
                ]
        except Exception:
            raise PiiEngineUnavailable("analysis failed") from None
        return _merge(results)

    def anonymize(
        self, text: str, findings: list[PiiFinding], placeholders: Mapping[str, str]
    ) -> str:
        if not findings:
            return text
        try:
            with self._lock:
                return self._anonymizer.anonymize(
                    text=text,
                    analyzer_results=[
                        RecognizerResult(f.entity_type, f.start, f.end, f.score) for f in findings
                    ],
                    operators={
                        f.entity_type: OperatorConfig(
                            "replace", {"new_value": placeholders[f.entity_type]}
                        )
                        for f in findings
                    },
                ).text
        except Exception:
            raise PiiEngineUnavailable("anonymization failed") from None


def _merge(results: list[RecognizerResult]) -> list[PiiFinding]:
    rank = {entity: index for index, entity in enumerate(PII_ENTITIES)}

    def stronger(a: RecognizerResult, b: RecognizerResult) -> RecognizerResult:
        if a.score != b.score:
            return a if a.score > b.score else b
        return a if rank[a.entity_type] <= rank[b.entity_type] else b

    merged: list[tuple[int, int, RecognizerResult]] = []
    for result in sorted(results, key=lambda r: (r.start, -r.end)):
        if merged and result.start < merged[-1][1]:
            start, end, best = merged[-1]
            merged[-1] = (start, max(end, result.end), stronger(best, result))
        else:
            merged.append((result.start, result.end, result))
    return [
        PiiFinding(entity_type=best.entity_type, start=start, end=end, score=min(best.score, 1.0))
        for start, end, best in merged
    ]


_engines: dict[tuple[str, ...], PiiEngine] = {}
_engines_lock = threading.Lock()


def get_engine(languages: tuple[str, ...]) -> PiiEngine:
    """Shared engine for these languages; built once, failures are not cached."""
    key = tuple(languages)
    with _engines_lock:
        engine = _engines.get(key)
        if engine is None:
            try:
                engine = PiiEngine(key)
            except PiiEngineUnavailable:
                raise
            except Exception:
                raise PiiEngineUnavailable("engine could not be built") from None
            _engines[key] = engine
        return engine


if __name__ == "__main__":
    engine = get_engine(SUPPORTED_LANGUAGES)
    sample = "Contact demo.user@example.test, PESEL 03610112347."
    findings = engine.analyze(sample, dict.fromkeys(PII_ENTITIES, 0.5))
    found = sorted({finding.entity_type for finding in findings})
    if found != ["EMAIL_ADDRESS", "PL_PESEL"]:
        raise SystemExit(f"Presidio check failed: found {found}")
    print(f"Presidio ready: languages {', '.join(SUPPORTED_LANGUAGES)} ({RECOGNIZERS_VERSION})")
