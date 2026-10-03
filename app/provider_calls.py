"""Run provider operations only after durable, policy-bounded reservations."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from app import budget
from app.adapters.jev import JevAdapter
from app.adapters.openai_luna import OpenAILunaAdapter, SummaryResult, TokenCount
from app.budget import BudgetLimits
from app.contracts import (
    BudgetUnit,
    CostStatus,
    RequestContext,
    Reservation,
    ReservationPurpose,
    ReservationState,
    SemanticResult,
    Usage,
)
from app.pricing import (
    PricingTable,
    price_jev_usage,
    price_openai_usage,
    reserve_jev_nusd,
    reserve_openai_nusd,
)

# Token counting is a provider request but has no token-generation charge. Reserve one nUSD
# as a temporary positive ledger marker so B3's durable provider-call quota counts the call;
# settle it to zero when the count endpoint responds. This is not included as spend.
_COUNT_CALL_LEDGER_MARKER_NUSD = 1


class ProviderCostUnavailable(RuntimeError):
    """A response arrived but there is not enough usage data to settle safely."""


class InputTokenLimitExceeded(RuntimeError):
    """The exact token count exceeds the active policy limit."""


async def assess_with_budget(
    *,
    db_path: Path,
    context: RequestContext,
    adapter: JevAdapter,
    state: Mapping[str, Any],
    limits: BudgetLimits,
    pricing: PricingTable,
    max_detector_input_tokens: int = 65_536,
) -> tuple[SemanticResult, Usage, UUID]:
    """Reserve Jev's configured worst-case input cost, call once, and settle actual usage."""
    amount = reserve_jev_nusd(pricing, max_input_tokens=max_detector_input_tokens)
    reservation = budget.reserve(
        db_path,
        context,
        ReservationPurpose.DETECTOR,
        BudgetUnit.NUSD,
        amount,
        limits,
        pricing_version=pricing.version,
    )
    budget.mark_started(db_path, reservation.reservation_id)
    try:
        result, raw_usage = await adapter.assess(state)
        priced_usage = price_jev_usage(raw_usage, pricing)
        if priced_usage.cost_nusd is None:
            raise ProviderCostUnavailable("Jev usage is unavailable")
        budget.settle(db_path, reservation.reservation_id, priced_usage.cost_nusd)
        return result, priced_usage, reservation.reservation_id
    except BaseException:
        _mark_unknown_if_open(db_path, reservation)
        raise


async def summarize_with_budget(
    *,
    db_path: Path,
    context: RequestContext,
    adapter: OpenAILunaAdapter,
    input: str,
    limits: BudgetLimits,
    pricing: PricingTable,
    max_input_tokens: int,
    max_output_tokens: int,
) -> tuple[TokenCount, SummaryResult, Usage, Usage, UUID, UUID]:
    """Count the complete input, reserve its worst-case cost, then call Luna once.

    Both count and generation receive the identical server-owned instructions and already-
    redacted input inside ``OpenAILunaAdapter``. A failed/uncertain provider call retains its
    reservation; an unavailable count prevents generation.
    """
    count_reservation = budget.reserve(
        db_path,
        context,
        ReservationPurpose.SUMMARY,
        BudgetUnit.NUSD,
        _COUNT_CALL_LEDGER_MARKER_NUSD,
        limits,
        pricing_version=pricing.version,
    )
    budget.mark_started(db_path, count_reservation.reservation_id)
    try:
        token_count = await adapter.count_input_tokens(input=input)
    except BaseException:
        _mark_unknown_if_open(db_path, count_reservation)
        raise
    budget.settle(db_path, count_reservation.reservation_id, 0)
    token_usage = token_count.usage.model_copy(
        update={
            "input_tokens": token_count.input_tokens,
            "output_tokens": 0,
            "cost_nusd": 0,
            "pricing_version": pricing.version,
            "cost_status": CostStatus.CALCULATED,
        }
    )
    if token_count.input_tokens > max_input_tokens:
        raise InputTokenLimitExceeded("summary input exceeds the configured token limit")

    amount = reserve_openai_nusd(token_count.input_tokens, max_output_tokens, pricing)
    summary_reservation = budget.reserve(
        db_path,
        context,
        ReservationPurpose.SUMMARY,
        BudgetUnit.NUSD,
        amount,
        limits,
        pricing_version=pricing.version,
    )
    budget.mark_started(db_path, summary_reservation.reservation_id)
    try:
        summary = await adapter.summarize(input=input)
        priced_usage = price_openai_usage(summary.usage, pricing)
        if priced_usage.cost_nusd is None:
            raise ProviderCostUnavailable("OpenAI usage is unavailable")
        budget.settle(db_path, summary_reservation.reservation_id, priced_usage.cost_nusd)
        return (
            token_count,
            summary,
            token_usage,
            priced_usage,
            count_reservation.reservation_id,
            summary_reservation.reservation_id,
        )
    except BaseException:
        _mark_unknown_if_open(db_path, summary_reservation)
        raise


def _mark_unknown_if_open(db_path, reservation: Reservation) -> None:
    """Best-effort conservative cleanup without masking the provider/control exception."""
    try:
        current = budget.get_reservation(db_path, reservation.reservation_id)
        if current.state in {ReservationState.RESERVED, ReservationState.STARTED}:
            budget.mark_unknown(db_path, reservation.reservation_id)
    except Exception:
        # Startup reconciliation will mark a stranded reservation UNKNOWN if cleanup fails.
        return
