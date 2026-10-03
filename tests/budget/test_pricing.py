import pytest

from app.contracts import CostStatus, Provider, Usage
from app.pricing import (
    DEFAULT_PRICING,
    price_jev_usage,
    price_openai_usage,
    reserve_jev_nusd,
    reserve_openai_nusd,
)


def usage(provider: Provider, **overrides: object) -> Usage:
    values: dict[str, object] = {
        "provider": provider,
        "requested_model": "jev-1.13.0" if provider is Provider.TYPESAFE else "gpt-6-luna",
        "model": "jev-1.13.0" if provider is Provider.TYPESAFE else "gpt-6-luna",
        "provider_response_id": "resp-test" if provider is Provider.OPENAI else None,
        "input_tokens": 100,
        "cached_input_tokens": None if provider is Provider.TYPESAFE else 10,
        "output_tokens": 20,
        "cost_nusd": None,
        "pricing_version": None,
        "cost_status": CostStatus.UNKNOWN,
    }
    values.update(overrides)
    return Usage(**values)


def test_jev_reservation_and_price_are_exact_integer_nusd() -> None:
    assert reserve_jev_nusd(DEFAULT_PRICING, max_input_tokens=65_536) == 2_752_512

    priced = price_jev_usage(usage(Provider.TYPESAFE), DEFAULT_PRICING)

    assert priced.cost_nusd == 4_200
    assert priced.pricing_version == DEFAULT_PRICING.version
    assert priced.cost_status is CostStatus.CALCULATED


def test_openai_reserves_cache_write_worst_case_and_all_output_tokens() -> None:
    # 100 * 125 nUSD input + 2048 * 500 nUSD output.
    assert reserve_openai_nusd(100, 2048, DEFAULT_PRICING) == 1_036_500
    # Cached 10 * 10, other input 90 * 125, output 20 * 500.
    priced = price_openai_usage(usage(Provider.OPENAI), DEFAULT_PRICING)
    assert priced.cost_nusd == 21_350
    assert priced.cost_status is CostStatus.ESTIMATED
    assert priced.pricing_version == DEFAULT_PRICING.version


def test_openai_missing_usage_stays_unknown() -> None:
    priced = price_openai_usage(usage(Provider.OPENAI, output_tokens=None), DEFAULT_PRICING)
    assert priced.cost_nusd is None
    assert priced.pricing_version is None
    assert priced.cost_status is CostStatus.UNKNOWN


def test_openai_long_context_uses_the_higher_published_rates() -> None:
    amount = reserve_openai_nusd(272_001, 2, DEFAULT_PRICING)
    assert amount == 272_001 * 250 + 2 * 750


def test_pricing_refuses_wrong_provider_and_invalid_amounts() -> None:
    with pytest.raises(ValueError, match="TypeSafe"):
        price_jev_usage(usage(Provider.OPENAI))
    with pytest.raises(ValueError, match="OpenAI"):
        price_openai_usage(usage(Provider.TYPESAFE))
    with pytest.raises(ValueError, match="max_output_tokens"):
        reserve_openai_nusd(10, 0)
    with pytest.raises(ValueError, match="confirmed Jev reservation envelope"):
        reserve_jev_nusd(DEFAULT_PRICING, max_input_tokens=1)
