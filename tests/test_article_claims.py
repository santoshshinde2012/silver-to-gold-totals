"""Lock every result the article quotes from the local run."""

from __future__ import annotations


def test_first_gold(result):
    assert result["gold_v0_rows"] == 5
    assert result["gold_v0_3nov_west"] == (125, 3, 2)


def test_a_move_has_an_old_and_a_new_row(result):
    assert result["move_7_change_rows"] == [
        ("update_preimage", "2026-11-03", "West"),
        ("update_postimage", "2026-11-04", "East"),
    ]
    assert result["new_groups_for_move"] == [("2026-11-04", "East")]
    assert result["old_and_new_groups_for_move"] == [("2026-11-03", "West"), ("2026-11-04", "East")]


def test_new_groups_only_leaves_the_old_group_and_the_empty_group(result):
    assert result["repairs"]["new groups, upsert"] == [
        ("2026-11-03", "West", (125, 3, 2), (100, 2, 2)),
        ("2026-11-05", "South", (90, 1, 1), None),
    ]


def test_upsert_cannot_remove_an_empty_group(result):
    assert result["repairs"]["old and new groups, upsert"] == [("2026-11-05", "South", (90, 1, 1), None)]


def test_replacing_old_and_new_groups_matches_a_full_rebuild(result):
    assert result["repairs"]["old and new groups, replace"] == []


def test_arithmetic_gets_sums_right_and_distinct_customers_wrong(result):
    assert result["repairs"]["add and subtract changed rows"] == [
        ("2026-11-03", "West", (100, 2, 1), (100, 2, 2)),
        ("2026-11-05", "South", (0, 0, 0), None),
    ]


def test_an_old_retry_overwrites_newer_totals_without_a_guard(result):
    assert result["race_guard_false"] == {
        "steps": ["released", "released"],
        "3nov_west": (100, 2, 2),
        "matches_full_rebuild": False,
    }


def test_the_guard_refuses_the_old_retry(result):
    assert result["race_guard_true"] == {
        "steps": ["released", "rejected"],
        "3nov_west": (95, 2, 2),
        "matches_full_rebuild": True,
    }
    assert result["3nov_west_full_rebuild"] == (95, 2, 2)


def test_closed_month_adjustment_keeps_the_report_total(result):
    c = result["closed_month"]
    assert (c["approved_october"], c["current_october"], c["silver_total"]) == (150, 145, 365)
    assert c["drop_late_rows_total"] == 370
    assert c["adjustments"] == [{"booked_in": "2026-11", "for_month": "2026-10", "amount": -5}]
    assert c["approved_plus_adjustments_total"] == 365
