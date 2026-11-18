"""The article's example, step by step. Returns every result the article quotes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import deltalake
import pandas as pd

from .models import OrderChange
from .pipeline import adjustments, build_release, publish
from .protocols import GoldRepair
from .repairs import ChangedRowArithmetic, NewGroupsUpsert, OldAndNewUpsert, ReplaceAffectedGroups
from .repository import GoldTotals, SilverOrders
from .totals import differences, full_rebuild, month_totals, new_groups, old_and_new_groups

CODE_ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = CODE_ROOT / "data" / "orders.json"


def _row(gold: pd.DataFrame, date: str, region: str) -> tuple[int, ...] | None:
    hit = gold[(gold["business_date"] == date) & (gold["region"] == region)]
    return tuple(int(x) for x in hit.iloc[0, 2:]) if len(hit) else None


def run(root: Path, seed_file: Path = SEED_FILE) -> dict[str, Any]:
    if root.exists():
        shutil.rmtree(root)
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    silver = SilverOrders(root)
    out: dict[str, Any] = {"deltalake": deltalake.__version__}

    # 0. Silver's first load and the Gold built from it.
    v0 = silver.first_load(seed["silver_first_load"])
    first_gold = full_rebuild(silver.read())
    out["gold_v0_rows"] = len(first_gold)
    out["gold_v0_3nov_west"] = _row(first_gold, "2026-11-03", "West")

    # 1. Two changes: order 7 moves, then order 8 is cancelled.
    v_move = silver.change(OrderChange(**seed["move_7"]))
    v_cancel = silver.change(OrderChange(**seed["cancel_8"]))
    feed = silver.changes(v0 + 1)
    out["move_7_change_rows"] = [
        (r["_change_type"], r["business_date"], r["region"]) for r in feed[feed["order_id"] == 7].to_dict("records")
    ]
    move = silver.changes(v_move, v_move)
    out["new_groups_for_move"] = sorted(new_groups(move))
    out["old_and_new_groups_for_move"] = sorted(old_and_new_groups(move))
    reference = full_rebuild(silver.read())

    # 2. Four ways to repair Gold, each on its own copy, compared with a full rebuild of Silver v2.
    out["repairs"] = {}
    repairs: list[GoldRepair] = [NewGroupsUpsert(), OldAndNewUpsert(), ReplaceAffectedGroups(), ChangedRowArithmetic()]
    for repair in repairs:
        gold = GoldTotals(root, "gold_" + repair.name.replace(" ", "_").replace(",", ""))
        gold.create(first_gold, v0)
        for v in (v_move, v_cancel):  # one repair after each Silver commit
            repair.apply(silver, gold, v, v)
        out["repairs"][repair.name] = differences(gold.read(), reference)

    # 3. Order 3 is corrected. A repair that read Silver v1 was interrupted; the repair that read v3 lands,
    #    then the old one is retried.
    v3 = silver.change(OrderChange(**seed["fix_3"]))
    reference = full_rebuild(silver.read())
    older = build_release(silver, v_move, v_move)
    newer = build_release(silver, v_move, v3)
    for guard in (False, True):
        gold = GoldTotals(root, f"gold_race_guard_{guard}".lower())
        gold.create(first_gold, v0)
        steps = [publish(gold, newer, guard), publish(gold, older, guard)]
        out[f"race_guard_{guard}".lower()] = {
            "steps": steps,
            "3nov_west": _row(gold.read(), "2026-11-03", "West"),
            "matches_full_rebuild": differences(gold.read(), reference) == [],
        }
    out["3nov_west_full_rebuild"] = _row(reference, "2026-11-03", "West")

    # 4. October was closed at Silver v3 (approved total 150).
    #    In November, order 2 (an October order) is corrected.
    approved = month_totals(reference)
    silver.change(OrderChange(**seed["fix_2_late"]))
    current = month_totals(full_rebuild(silver.read()))
    late_dropped = {**current, seed["closed_month"]: approved[seed["closed_month"]]}
    adj = adjustments(approved, current, [seed["closed_month"]], booked_in="2026-11")
    out["closed_month"] = {
        "approved_october": approved["2026-10"],
        "current_october": current["2026-10"],
        "silver_total": sum(current.values()),
        "drop_late_rows_total": sum(late_dropped.values()),
        "adjustments": adj,
        "approved_plus_adjustments_total": sum(late_dropped.values()) + sum(a["amount"] for a in adj),
    }
    return out
