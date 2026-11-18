"""Column names, the Gold grain, and small value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

#: The Gold grain: one row per business date and region.
GROUP = ["business_date", "region"]
ORDER_COLUMNS = ["order_id", "business_date", "region", "customer", "amount", "status"]
GOLD_COLUMNS = GROUP + ["net_amount", "order_count", "customers"]


@dataclass(frozen=True)
class OrderChange:
    """One change to one Silver order: which order, and which columns get which values."""

    order_id: int
    updates: dict[str, Any] = field(default_factory=dict)


class Adjustment(TypedDict):
    """A correction to a closed month, booked in a later month instead of restating it."""

    booked_in: str
    for_month: str
    amount: int


@dataclass(frozen=True)
class Release:
    """A repair ready to publish: the Gold rows for its groups, and the Silver version it read."""

    groups: frozenset[tuple[str, str]]
    rows: list[dict[str, Any]]
    silver_version: int
