"""HTTPX adapter for TypeSafe Jev. It deliberately performs no automatic retries."""

from collections.abc import Mapping
from typing import Any

import httpx

from app.contracts import CostStatus, Provider, SemanticResult, Usage
from app.prompts.semantic import SEMANTIC_QUESTIONS

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
JEV_TIMEOUT_SECONDS = 10.0


class JevAdapterError(RuntimeError):
    """Safe-to-surface provider failure; never contains provider body or submitted text."""


class JevAdapter:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = JEV_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TypeSafe API key is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    async def assess(self, state: Mapping[str, Any]) -> tuple[SemanticResult, Usage]:
        """Score already-redacted state; authorization and redaction belong to the gateway."""
        body = {
            "state": dict(state),
            "model": JEV_MODEL,
            "questions": SEMANTIC_QUESTIONS,
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    JEV_ENDPOINT,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=False
                ) as client:
                    response = await client.post(
                        JEV_ENDPOINT,
                        json=body,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
            response.raise_for_status()
            payload = response.json()
            return _parse_response(payload)
        except JevAdapterError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            # Do not include the exception string: SDK/HTTP errors can contain request details.
            raise JevAdapterError(type(exc).__name__) from None


def _parse_response(payload: object) -> tuple[SemanticResult, Usage]:
    if not isinstance(payload, dict):
        raise JevAdapterError("invalid response shape")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevAdapterError("missing answers")
    override = _noul_value(answers, "instruction_override")
    exfiltration = _noul_value(answers, "data_exfiltration")
    score = max(override, exfiltration)
    # The category is set to benign below the policy threshold by semantic.evaluate().
    result = SemanticResult(
        instruction_override_probability=override,
        data_exfiltration_probability=exfiltration,
        risk_score=score,
        category="instruction_override" if override >= exfiltration else "data_exfiltration",
    )
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        raw_usage = {}
    usage = Usage(
        provider=Provider.TYPESAFE,
        requested_model=JEV_MODEL,
        model=_optional_token(payload.get("model")),
        provider_response_id=None,
        input_tokens=_optional_count(raw_usage.get("input_tokens")),
        cached_input_tokens=None,
        output_tokens=_optional_count(raw_usage.get("output_tokens")),
        cost_nusd=None,
        pricing_version=None,
        cost_status=CostStatus.UNKNOWN,
    )
    return result, usage


def _noul_value(answers: dict[str, Any], name: str) -> float:
    answer = answers.get(name)
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise JevAdapterError(f"invalid Noul answer: {name}")
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JevAdapterError(f"invalid Noul value: {name}")
    # SemanticResult validates finite values in [0, 1].
    return float(value)


def _optional_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JevAdapterError("invalid token usage")
    return value


def _optional_token(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise JevAdapterError("invalid model metadata")
    return value
