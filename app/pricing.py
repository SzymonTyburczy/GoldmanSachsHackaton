"""Versioned, conservative token pricing used by budget reservations and settlement.

Rates use integer nUSD per token (1 USD = 1_000_000_000 nUSD). The source snapshots
below are Standard text rates for the named model versions on 2026-10-03. Regional,
Fast, Batch and Flex processing are not enabled by ControlProof.
"""

from dataclasses import dataclass

from app.contracts import CostStatus, Provider, Usage

OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
TYPESAFE_PRICING_SOURCE = "https://docs.typesafe.ai/models"
# Confirmed supported input envelope for the configured Jev adapter/model.
JEV_MIN_RESERVED_INPUT_TOKENS = 65_536


@dataclass(frozen=True)
class PricingTable:
    """Verified rates for the specific provider/model mode used by this application."""

    version: str
    typesafe_model: str
    openai_model: str
    typesafe_input_nusd_per_token: int
    openai_input_nusd_per_token: int
    openai_cached_input_nusd_per_token: int
    openai_cache_write_nusd_per_token: int
    openai_output_nusd_per_token: int
    openai_long_context_threshold: int = 272_000
    openai_long_input_nusd_per_token: int = 200
    openai_long_cached_input_nusd_per_token: int = 20
    openai_long_cache_write_nusd_per_token: int = 250
    openai_long_output_nusd_per_token: int = 750

    def __post_init__(self) -> None:
        values = (
            self.typesafe_input_nusd_per_token,
            self.openai_input_nusd_per_token,
            self.openai_cached_input_nusd_per_token,
            self.openai_cache_write_nusd_per_token,
            self.openai_output_nusd_per_token,
            self.openai_long_context_threshold,
            self.openai_long_input_nusd_per_token,
            self.openai_long_cached_input_nusd_per_token,
            self.openai_long_cache_write_nusd_per_token,
            self.openai_long_output_nusd_per_token,
        )
        if (
            not self.version
            or not self.typesafe_model
            or not self.openai_model
            or any(type(rate) is not int or rate < 0 for rate in values)
        ):
            raise ValueError("pricing version and integer rates are required")
        if self.openai_long_context_threshold <= 0:
            raise ValueError("long-context threshold must be positive")


# Standard, short-context text pricing as published on the source pages above.
# TypeSafe: $0.042 / 1M input tokens; output tokens have no charge.
# OpenAI gpt-6-luna: $0.10 / 1M input, $0.01 cached, $0.125 cache-write,
# $0.50 output. The 272k+ rate table is included for explicit future use; current policy
# caps summary input at 8192 tokens and therefore stays in the short-context tier.
DEFAULT_PRICING = PricingTable(
    version="standard-2026-10-03",
    typesafe_model="jev-1.13.0",
    openai_model="gpt-6-luna",
    typesafe_input_nusd_per_token=42,
    openai_input_nusd_per_token=100,
    openai_cached_input_nusd_per_token=10,
    openai_cache_write_nusd_per_token=125,
    openai_output_nusd_per_token=500,
)


def reserve_jev_nusd(
    pricing: PricingTable = DEFAULT_PRICING, *, max_input_tokens: int = 65_536
) -> int:
    """Conservative maximum for Jev's one-input, two-question request."""
    _positive_int(max_input_tokens, "max_input_tokens")
    if max_input_tokens < JEV_MIN_RESERVED_INPUT_TOKENS:
        raise ValueError("max_input_tokens is below the confirmed Jev reservation envelope")
    return max_input_tokens * pricing.typesafe_input_nusd_per_token


def reserve_openai_nusd(
    input_tokens: int,
    max_output_tokens: int,
    pricing: PricingTable = DEFAULT_PRICING,
) -> int:
    """Reserve worst-case OpenAI text cost, including possible cache writes."""
    _non_negative_int(input_tokens, "input_tokens")
    _positive_int(max_output_tokens, "max_output_tokens")
    if input_tokens > pricing.openai_long_context_threshold:
        input_rate = max(
            pricing.openai_long_input_nusd_per_token,
            pricing.openai_long_cache_write_nusd_per_token,
        )
        output_rate = pricing.openai_long_output_nusd_per_token
    else:
        input_rate = max(
            pricing.openai_input_nusd_per_token,
            pricing.openai_cache_write_nusd_per_token,
        )
        output_rate = pricing.openai_output_nusd_per_token
    return input_tokens * input_rate + max_output_tokens * output_rate


def price_jev_usage(usage: Usage, pricing: PricingTable = DEFAULT_PRICING) -> Usage:
    """Attach the exact Jev input charge when full provider token usage is available."""
    if usage.provider is not Provider.TYPESAFE or usage.requested_model != pricing.typesafe_model:
        raise ValueError("usage does not match the TypeSafe model in this pricing table")
    if usage.input_tokens is None:
        return usage.model_copy(
            update={"cost_nusd": None, "pricing_version": None, "cost_status": CostStatus.UNKNOWN}
        )
    amount = usage.input_tokens * pricing.typesafe_input_nusd_per_token
    status = CostStatus.CALCULATED if usage.output_tokens is not None else CostStatus.ESTIMATED
    return usage.model_copy(
        update={
            "cost_nusd": amount,
            "pricing_version": pricing.version,
            "cost_status": status,
        }
    )


def price_openai_usage(usage: Usage, pricing: PricingTable = DEFAULT_PRICING) -> Usage:
    """Estimate Luna spend conservatively where cache-write usage is not itemized.

    Cached input uses the published cached rate. Other input tokens use the larger of the
    ordinary input and cache-write rates because the API does not report a separate count
    for cache writes. The result is explicitly ``estimated``, not an invoice amount.
    """
    if usage.provider is not Provider.OPENAI or usage.requested_model != pricing.openai_model:
        raise ValueError("usage does not match the OpenAI model in this pricing table")
    if usage.input_tokens is None or usage.output_tokens is None:
        return usage.model_copy(
            update={"cost_nusd": None, "pricing_version": None, "cost_status": CostStatus.UNKNOWN}
        )
    cached = usage.cached_input_tokens
    if cached is None:
        cached = 0
    if cached > usage.input_tokens:
        raise ValueError("cached input tokens exceed total input tokens")

    if usage.input_tokens > pricing.openai_long_context_threshold:
        cached_rate = pricing.openai_long_cached_input_nusd_per_token
        uncached_rate = max(
            pricing.openai_long_input_nusd_per_token,
            pricing.openai_long_cache_write_nusd_per_token,
        )
        output_rate = pricing.openai_long_output_nusd_per_token
    else:
        cached_rate = pricing.openai_cached_input_nusd_per_token
        uncached_rate = max(
            pricing.openai_input_nusd_per_token,
            pricing.openai_cache_write_nusd_per_token,
        )
        output_rate = pricing.openai_output_nusd_per_token
    amount = (
        cached * cached_rate
        + (usage.input_tokens - cached) * uncached_rate
        + usage.output_tokens * output_rate
    )
    # Cache writes cannot be isolated from total uncached input usage in this response.
    return usage.model_copy(
        update={
            "cost_nusd": amount,
            "pricing_version": pricing.version,
            "cost_status": CostStatus.ESTIMATED,
        }
    )


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
