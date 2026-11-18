"""Composition root: run the Gold totals example on local Delta tables and print what happened.

Run from the repository root:  python -m src.totals_demo
"""

from __future__ import annotations

from typing import Any

from .scenario import CODE_ROOT, run


def report(out: dict[str, Any]) -> list[str]:
    """The lines the article quotes, in order. Each Gold value is (amount, orders, distinct customers)."""
    lines = [
        f"deltalake {out['deltalake']} on local disk; not a Databricks runtime",
        f"0. Gold from Silver v0: {out['gold_v0_rows']} groups; "
        f"3 Nov West = {out['gold_v0_3nov_west']} (amount, orders, customers)",
        f"1. Order 7 change rows: {out['move_7_change_rows']}",
        f"   Groups from new rows only: {out['new_groups_for_move']}",
        f"   Groups from old and new rows: {out['old_and_new_groups_for_move']}",
        "2. Differences from a full rebuild (group, Gold, full rebuild):",
    ]
    lines += [f"   {name}: {diff if diff else 'none'}" for name, diff in out["repairs"].items()]
    for guard in ("false", "true"):
        r = out[f"race_guard_{guard}"]
        lines.append(
            f"3. Race, guard={guard}: {r['steps']}; 3 Nov West = {r['3nov_west']}; "
            f"matches full rebuild: {r['matches_full_rebuild']}"
        )
    c = out["closed_month"]
    lines += [
        f"   3 Nov West in a full rebuild = {out['3nov_west_full_rebuild']}",
        f"4. October approved {c['approved_october']}, now {c['current_october']}. Silver total {c['silver_total']}.",
        f"   Drop late rows: report total {c['drop_late_rows_total']}",
        f"   Keep October, book an adjustment {c['adjustments']}: report total {c['approved_plus_adjustments_total']}",
    ]
    return lines


def main() -> None:
    for line in report(run(CODE_ROOT / "lake")):
        print(line)


if __name__ == "__main__":
    main()
