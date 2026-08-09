from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SignalResult:
    average: Decimal | None
    ratio: Decimal | None
    status: str
    count: int


def evaluate_turnover(
    current: Decimal,
    baseline: Iterable[Decimal],
    *,
    minimum_count: int,
    min_ratio: Decimal,
    max_ratio: Decimal,
) -> SignalResult:
    values = [Decimal(value) for value in baseline if value is not None]
    if len(values) < minimum_count:
        return SignalResult(None, None, "insufficient", len(values))

    average = sum(values, Decimal("0")) / Decimal(len(values))
    if average <= 0:
        return SignalResult(average, None, "insufficient", len(values))

    ratio = Decimal(current) / average
    if min_ratio <= ratio <= max_ratio:
        status = "signal"
    elif ratio > max_ratio:
        status = "above_range"
    else:
        status = "normal"
    return SignalResult(average, ratio, status, len(values))
