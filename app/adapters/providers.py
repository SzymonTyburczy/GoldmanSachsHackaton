"""Jev and Luna adapters configured for one request.

The gateway is the only caller. Keys come from the server environment; timeouts and the
output limit come from the policy pinned for the request. A missing key leaves the
provider unavailable, and the gateway then refuses before reading the document.
"""

from dataclasses import dataclass
from typing import Protocol

from app.adapters.jev import JevAdapter
from app.adapters.openai_luna import OpenAILunaAdapter, SummaryResult, TokenCount
from app.controls.semantic import SemanticEvaluator
from app.policy import ModelsPolicy
from app.settings import Settings


class Summarizer(Protocol):
    async def count_input_tokens(self, *, input: str) -> TokenCount: ...

    async def summarize(self, *, input: str, **options: int) -> SummaryResult: ...


@dataclass(frozen=True)
class ProviderSet:
    detector: SemanticEvaluator | None
    summarizer: Summarizer | None


class Providers(Protocol):
    def connect(self, models: ModelsPolicy) -> ProviderSet: ...


class KeyedProviders:
    """Paweł's adapters with the local API keys; neither retries on its own."""

    def __init__(self, settings: Settings) -> None:
        self._typesafe_key = settings.typesafe_api_key
        self._openai_key = settings.openai_api_key

    def connect(self, models: ModelsPolicy) -> ProviderSet:
        detector = None
        if self._typesafe_key is not None:
            detector = JevAdapter(
                self._typesafe_key.get_secret_value(),
                timeout=float(models.detector_timeout_seconds),
            )
        summarizer = None
        if self._openai_key is not None:
            summarizer = OpenAILunaAdapter(
                self._openai_key.get_secret_value(),
                timeout=float(models.summary_timeout_seconds),
                max_output_tokens=models.summary_max_output_tokens,
            )
        return ProviderSet(detector, summarizer)
