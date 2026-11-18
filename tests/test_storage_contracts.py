"""Run domain contracts against independent memory adapters and real Delta tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.models import GOLD_COLUMNS, OrderChange
from src.pipeline import build_release, publish
from src.repository import GoldTotals, SilverOrders
from src.totals import full_rebuild, restrict
from tests.fakes import MemoryOrders, MemoryTotals

ROWS = [
    {
        "order_id": 1,
        "business_date": "2026-11-01",
        "region": "O'Brien",
        "customer": "A",
        "amount": 10,
        "status": "accepted",
    },
    {
        "order_id": 2,
        "business_date": "2026-11-02",
        "region": "East",
        "customer": "B",
        "amount": 20,
        "status": "accepted",
    },
]


@pytest.fixture(params=["memory", "delta"])
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, Any]:
    if request.param == "delta":
        silver, gold = SilverOrders(tmp_path), GoldTotals(tmp_path)
    else:
        silver, gold = MemoryOrders(), MemoryTotals()
    silver.first_load(ROWS)
    gold.create(full_rebuild(silver.read()), 0)
    return silver, gold


def test_order_snapshots_and_cdf_are_versioned_and_reads_are_isolated(stores):
    silver, _ = stores
    silver.change(OrderChange(1, {"region": "East", "amount": 11}))
    assert silver.version() == 1
    assert silver.read(0).to_dict("records") == ROWS
    assert silver.read(1).iloc[0]["amount"] == 11
    feed = silver.changes(1, 1)
    assert feed[["_change_type", "region", "amount"]].to_dict("records") == [
        {"_change_type": "update_preimage", "region": "O'Brien", "amount": 10},
        {"_change_type": "update_postimage", "region": "East", "amount": 11},
    ]
    assert set(feed["_commit_version"]) == {1}
    copy = silver.read(0)
    copy.loc[0, "amount"] = 999
    assert silver.read(0).iloc[0]["amount"] == 10


def test_upsert_keeps_absent_groups_and_release_metadata(stores):
    _, gold = stores
    changed = gold.read().iloc[[0]].copy()
    changed.loc[:, "net_amount"] = 12
    gold.upsert(changed)
    assert gold.read()["net_amount"].tolist() == [12, 20]
    assert gold.last_silver_version() == 0
    gold.upsert(pd.DataFrame(columns=GOLD_COLUMNS))
    assert gold.read()["net_amount"].tolist() == [12, 20]


def test_group_replacement_handles_quoted_keys_and_removes_empty_groups(stores):
    _, gold = stores
    gold.replace_groups(frozenset({("2026-11-01", "O'Brien")}), pd.DataFrame(columns=GOLD_COLUMNS), 1)
    assert gold.read()["region"].tolist() == ["East"]
    assert gold.last_silver_version() == 1
    # A valid empty scope changes no rows and can still record the input watermark.
    before = gold.read()
    gold.replace_groups(frozenset(), pd.DataFrame(columns=GOLD_COLUMNS), 2)
    assert_frame_equal(gold.read(), before)
    assert gold.last_silver_version() == 2


def test_replacement_rejects_outside_rows_without_mutating_data_or_history(stores):
    _, gold = stores
    before = gold.read()
    with pytest.raises(ValueError, match="[Ss]cope|groups"):
        gold.replace_groups(frozenset({("2026-11-01", "O'Brien")}), before, 9)
    assert_frame_equal(gold.read(), before)
    assert gold.last_silver_version() == 0


def test_duplicate_gold_grain_is_rejected_before_writing(stores):
    _, gold = stores
    before = gold.read()
    with pytest.raises(ValueError):
        gold.upsert(pd.concat([before, before]))
    assert_frame_equal(gold.read(), before)


def test_empty_release_deletes_last_group_and_guard_rejects_same_or_older_version(stores):
    silver, gold = stores
    silver.change(OrderChange(1, {"status": "cancelled"}))
    silver.change(OrderChange(2, {"status": "cancelled"}))
    release = build_release(silver, 1, 2)
    assert release.rows == []
    assert publish(gold, release, guard=True) == "released"
    assert list(gold.read().columns) == GOLD_COLUMNS
    assert gold.read().empty
    assert gold.last_silver_version() == 2
    assert publish(gold, release, guard=True) == "rejected"
    assert publish(gold, build_release(silver, 1, 1), guard=True) == "rejected"


def test_guarded_publication_works_without_read_or_upsert_capabilities(stores):
    silver, gold = stores

    class PublisherOnly:
        replace_groups = gold.replace_groups
        last_silver_version = gold.last_silver_version

    silver.change(OrderChange(1, {"amount": 8}))
    assert publish(PublisherOnly(), build_release(silver, 1, 1), guard=True) == "released"
    assert gold.read()["net_amount"].tolist() == [8, 20]


def test_empty_change_feed_preserves_schema_and_leaves_gold_rows(stores):
    silver, gold = stores

    class EmptyFeedReader:
        read = silver.read

        def changes(self, start: int, end: int | None = None) -> pd.DataFrame:
            return silver.changes(0, 0).iloc[0:0]

    before = gold.read()
    release = build_release(EmptyFeedReader(), 0, 0)
    assert release.groups == frozenset()
    assert release.rows == []
    assert publish(gold, release, guard=False) == "released"
    assert_frame_equal(gold.read(), before)


def test_empty_restrict_keeps_columns():
    empty = pd.DataFrame(columns=GOLD_COLUMNS)
    assert list(restrict(empty, frozenset()).columns) == GOLD_COLUMNS


def test_delta_update_escapes_literals_and_validates_columns(tmp_path):
    silver = SilverOrders(tmp_path)
    silver.first_load(ROWS)
    silver.change(OrderChange(2, {"region": "King's East"}))
    assert silver.read().iloc[1]["region"] == "King's East"
    version = silver.version()
    for change in [OrderChange(1, {"order_id": 2}), OrderChange(1, {"unknown": "x"}), OrderChange(1, {"amount": "x"})]:
        with pytest.raises(ValueError):
            silver.change(change)
    assert silver.version() == version
