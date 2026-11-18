"""The Gold query, the affected groups, and comparisons. Pure pandas, no storage."""

from __future__ import annotations

import pandas as pd

from .models import GOLD_COLUMNS, GROUP


def full_rebuild(orders: pd.DataFrame) -> pd.DataFrame:
    """The reference answer: daily totals of accepted orders by business date and region."""
    accepted = orders[orders["status"] == "accepted"]
    if accepted.empty:
        return pd.DataFrame(columns=GOLD_COLUMNS)
    out = accepted.groupby(GROUP, as_index=False).agg(
        net_amount=("amount", "sum"), order_count=("order_id", "count"), customers=("customer", "nunique")
    )
    return tidy(out)


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Gold columns as whole numbers, sorted by the grain."""
    df = df[GOLD_COLUMNS].copy()
    for c in ["net_amount", "order_count", "customers"]:
        df[c] = df[c].astype("int64")
    return df.sort_values(GROUP).reset_index(drop=True)


def groups_of(rows: pd.DataFrame) -> frozenset[tuple[str, str]]:
    """The (business date, region) groups that a set of rows belongs to."""
    return frozenset(zip(rows["business_date"], rows["region"], strict=True))


def new_groups(changes: pd.DataFrame) -> frozenset[tuple[str, str]]:
    """Groups named by the new state of each changed row only."""
    return groups_of(changes[changes["_change_type"].isin(["insert", "update_postimage"])])


def old_and_new_groups(changes: pd.DataFrame) -> frozenset[tuple[str, str]]:
    """Groups named by the old state and the new state of each changed row."""
    return groups_of(changes)


def restrict(totals: pd.DataFrame, groups: frozenset[tuple[str, str]]) -> pd.DataFrame:
    """Keep only the rows of the given groups."""
    keep = [g in groups for g in zip(totals["business_date"], totals["region"], strict=True)]
    return totals[keep].reset_index(drop=True)


def differences(
    gold: pd.DataFrame, reference: pd.DataFrame
) -> list[tuple[str, str, tuple[int, ...] | None, tuple[int, ...] | None]]:
    """Groups where Gold and the full rebuild disagree, with both values. Missing rows count too."""
    g = gold.set_index(GROUP)
    r = reference.set_index(GROUP)
    out = []
    for key in sorted(set(g.index) | set(r.index)):
        gv = tuple(int(x) for x in g.loc[key]) if key in g.index else None
        rv = tuple(int(x) for x in r.loc[key]) if key in r.index else None
        if gv != rv:
            out.append((key[0], key[1], gv, rv))
    return out


def month_totals(totals: pd.DataFrame) -> dict[str, int]:
    """Net amount per calendar month, for the closed-month example."""
    m = totals.assign(month=totals["business_date"].str[:7]).groupby("month")["net_amount"].sum()
    return {k: int(v) for k, v in m.items()}
