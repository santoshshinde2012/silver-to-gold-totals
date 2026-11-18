"""Unit tests for the Gold query and helpers, with no storage."""

from __future__ import annotations

import pandas as pd

from src.pipeline import adjustments
from src.totals import differences, full_rebuild, new_groups, old_and_new_groups, restrict

ORDERS = pd.DataFrame(
    [
        {
            "order_id": 1,
            "business_date": "2026-11-01",
            "region": "X",
            "customer": "A",
            "amount": 5,
            "status": "accepted",
        },
        {
            "order_id": 2,
            "business_date": "2026-11-01",
            "region": "X",
            "customer": "A",
            "amount": 7,
            "status": "cancelled",
        },
        {
            "order_id": 3,
            "business_date": "2026-11-02",
            "region": "Y",
            "customer": "B",
            "amount": 9,
            "status": "accepted",
        },
    ]
)
FEED = pd.DataFrame(
    [
        {"_change_type": "update_preimage", "business_date": "2026-11-01", "region": "X"},
        {"_change_type": "update_postimage", "business_date": "2026-11-02", "region": "Y"},
    ]
)


def test_full_rebuild_counts_accepted_orders_only() -> None:
    assert full_rebuild(ORDERS).to_dict("records") == [
        {"business_date": "2026-11-01", "region": "X", "net_amount": 5, "order_count": 1, "customers": 1},
        {"business_date": "2026-11-02", "region": "Y", "net_amount": 9, "order_count": 1, "customers": 1},
    ]


def test_new_rows_name_only_the_new_group() -> None:
    assert new_groups(FEED) == frozenset({("2026-11-02", "Y")})
    assert old_and_new_groups(FEED) == frozenset({("2026-11-01", "X"), ("2026-11-02", "Y")})


def test_restrict_and_differences() -> None:
    totals = full_rebuild(ORDERS)
    only_x = restrict(totals, frozenset({("2026-11-01", "X")}))
    assert len(only_x) == 1
    assert differences(only_x, totals) == [("2026-11-02", "Y", None, (9, 1, 1))]


def test_adjustments_only_for_closed_months_that_moved() -> None:
    assert adjustments({"2026-10": 10}, {"2026-10": 10}, ["2026-10"], "2026-11") == []
    assert adjustments({"2026-10": 10}, {"2026-10": 8}, ["2026-10"], "2026-11") == [
        {"booked_in": "2026-11", "for_month": "2026-10", "amount": -2}
    ]
