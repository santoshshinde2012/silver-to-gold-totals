"""Export actual Delta snapshots to an offline HTML report and JSON, without changing the lake."""

from __future__ import annotations

import argparse
import html
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import deltalake
import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable
from deltalake.exceptions import DeltaError

from .models import GOLD_COLUMNS, ORDER_COLUMNS
from .totals import differences, full_rebuild

COMPARISONS = {
    "gold_new_groups_upsert": "New groups · upsert",
    "gold_old_and_new_groups_upsert": "Old + new groups · upsert",
    "gold_old_and_new_groups_replace": "Old + new groups · replace",
    "gold_add_and_subtract_changed_rows": "Changed-row arithmetic",
    "gold_race_guard_false": "Replay · guard disabled",
    "gold_race_guard_true": "Replay · guard enabled",
}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def inspect_lake(root: Path, repair_version: int = 2, race_version: int = 3) -> dict[str, Any]:
    """Read each Delta table at its captured version, then reconcile known demo stages.

    There is no transaction across tables. Stop writers before exporting. Historical
    references can be unavailable after vacuum; those checks are marked unavailable.
    Other project schemas remain inspectable, without inventing a schema mapping.
    """
    if not root.is_dir():
        raise ValueError(f"Lake directory does not exist: {root}")
    tables: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(root.iterdir()):
        if not (path / "_delta_log").is_dir():
            continue
        table = DeltaTable(str(path))
        frame = table.to_pandas()
        keys = [c for c in ["order_id", "seq", "business_date", "order_date", "region", "status"] if c in frame]
        if keys:
            frame = frame.sort_values(keys).reset_index(drop=True)
        frames[path.name] = frame
        tables[path.name] = {
            "version": table.version(),
            "row_count": len(frame),
            "columns": list(frame.columns),
            "records": _records(frame),
            "last_recorded_silver_version": next(
                (int(c["silver_version"]) for c in table.history() if "silver_version" in c), None
            ),
        }
    if not tables:
        raise ValueError(f"No Delta tables found in {root}")

    silver = frames.get("silver_orders")
    compatible = silver is not None and set(ORDER_COLUMNS).issubset(silver.columns)
    references: dict[str, Any] = {}
    checks = []
    if compatible:
        assert silver is not None
        references["latest"] = {
            "silver_version": tables["silver_orders"]["version"],
            "records": _records(full_rebuild(silver)),
        }
        for stage, version in (("repair", repair_version), ("race", race_version)):
            reference: dict[str, Any] = {"silver_version": version, "available": False}
            try:
                orders = DeltaTable(str(root / "silver_orders"), version=version).to_pandas()
                rows = full_rebuild(orders)
                reference.update(available=True, records=_records(rows))
            except (DeltaError, OSError) as exc:
                reference["reason"] = str(exc)
            references[stage] = reference
        for name, label in COMPARISONS.items():
            if name not in frames:
                continue
            stage = "race" if name.startswith("gold_race_") else "repair"
            ref = references[stage]
            check: dict[str, Any] = {
                "table": name,
                "label": label,
                "reference_silver_version": ref["silver_version"],
                "available": ref["available"],
            }
            if ref["available"]:
                diff = differences(frames[name][GOLD_COLUMNS], pd.DataFrame(ref["records"], columns=GOLD_COLUMNS))
                check.update(matches_full_rebuild=not diff, differing_groups=len(diff), differences=diff)
            checks.append(check)
    return {
        "source": str(root.resolve()),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": "silver-to-gold" if compatible else "external",
        "data": "Actual local Delta snapshots; demo inputs are synthetic",
        "runtime": {
            "python": platform.python_version(),
            "deltalake": deltalake.__version__,
            "pandas": pd.__version__,
            "pyarrow": pa.__version__,
        },
        "tables": tables,
        "references": references,
        "checks": checks,
    }


def _table(records: list[dict[str, Any]], columns: list[str]) -> str:
    headings = "".join(f"<th>{html.escape(c.replace('_', ' '))}</th>" for c in columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[c]))}</td>" for c in columns) + "</tr>" for row in records
    )
    return f'<div class="scroll"><table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table></div>'


def _panel(title: str, detail: str, body: str) -> str:
    return (
        f'<article class="panel"><div class="panel-title"><h2>{html.escape(title)}</h2>'
        f"<p>{html.escape(detail)}</p></div>{body}</article>"
    )


def render_report(snapshot: dict[str, Any]) -> str:
    """Present captured records and version-specific checks with no external assets."""
    tables = snapshot["tables"]
    known = snapshot["schema"] == "silver-to-gold"
    title = "Silver → Gold totals" if known else "External lake · table inspection"
    subtitle = (
        "Actual persisted rows and repair outcomes, reconciled against the Silver version for each demo stage."
        if known
        else "Actual persisted rows. This lake uses a different schema; Silver-to-Gold repair checks are not applied."
    )
    metrics: list[tuple[Any, str, str]] = []
    if known:
        silver = tables["silver_orders"]
        latest = snapshot["references"]["latest"]
        metrics = [
            (silver["row_count"], "Silver orders", f"Current snapshot · v{silver['version']}"),
            (
                sum(r["net_amount"] for r in latest["records"]),
                "Current accepted amount",
                "Full rebuild of latest Silver",
            ),
            (
                len([c for c in snapshot["checks"] if not c["table"].startswith("gold_race_")]),
                "Repair strategies",
                f"Compared with Silver v{snapshot['references']['repair']['silver_version']}",
            ),
            (
                len([c for c in snapshot["checks"] if c["table"].startswith("gold_race_")]),
                "Release replays",
                f"Compared with Silver v{snapshot['references']['race']['silver_version']}",
            ),
        ]
    else:
        metrics = [
            (t["row_count"], name.replace("_", " "), f"Delta version {t['version']}") for name, t in tables.items()
        ]
    cards = "".join(
        f'<div class="metric"><strong>{value}</strong><span>{html.escape(label)}</span>'
        f"<small>{html.escape(detail)}</small></div>"
        for value, label, detail in metrics
    )

    comparison = ""
    if known:
        rows = []
        for check in snapshot["checks"]:
            available = check["available"]
            matches = check.get("matches_full_rebuild", False)
            badge = "MATCH" if matches else ("DIFFERS" if available else "UNAVAILABLE")
            tone = "ok" if matches else "warn"
            count = str(check["differing_groups"]) if available else "—"
            rows.append(
                f"<tr><td>{html.escape(check['label'])}</td>"
                f"<td>v{check['reference_silver_version']}</td>"
                f'<td><b class="{tone}">{badge}</b></td><td>{count}</td></tr>'
            )
        comparison = _panel(
            "Reconciliation · each stage has its own baseline",
            "Three repair strategies and the unguarded replay intentionally demonstrate incorrect results.",
            "<table><thead><tr><th>Persisted Gold variant</th><th>Silver reference</th>"
            "<th>Result</th><th>Differing groups</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>",
        )

    if known:
        selected = ["silver_orders", "gold_old_and_new_groups_replace"]
    else:
        # Put the two serving layers together; retained event history is available
        # below without pushing the current result tables out of the overview.
        selected = [n for n in ("silver_orders", "gold_daily_order_totals") if n in tables]
        selected += [n for n in tables if n not in selected]
    panels: list[str] = []
    additional: list[str] = []
    for name in selected:
        if name not in tables:
            continue
        table = tables[name]
        label = "Silver · latest orders" if known and name == "silver_orders" else name.replace("_", " ")
        if known and name == "gold_old_and_new_groups_replace":
            label = "Gold · replace affected groups"
        detail = f"Delta v{table['version']} · {table['row_count']} rows · {name}"
        if known and name.startswith("gold_"):
            detail += f" · repair stage: Silver v{snapshot['references']['repair']['silver_version']}"
        body = _table(table["records"], table["columns"])
        if not known and len(panels) >= 2:
            additional.append(f'<details class="panel"><summary>{html.escape(detail)}</summary>{body}</details>')
        else:
            panels.append(_panel(label, detail, body))

    inventory = _table(
        [
            {
                "table": n,
                "delta_version": t["version"],
                "rows": t["row_count"],
                "recorded_silver_version": t["last_recorded_silver_version"],
            }
            for n, t in tables.items()
        ],
        ["table", "delta_version", "rows", "recorded_silver_version"],
    )
    runtime = " · ".join(f"{name} {version}" for name, version in snapshot["runtime"].items())
    note = (
        "Gold variants are retained at different demo stages; they are not all expected to match the latest Silver. "
        "An upsert does not update the source-version metadata in this teaching example."
        if known
        else "This schema has no business_date/region/amount/customer contract. "
        "No conversion or Gold repair was performed."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — actual Delta results</title><style>
* {{ box-sizing:border-box; }} body {{ margin:0;background:#f1f5f8;color:#183342;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1480px;padding:36px 42px;margin:auto; }}
.eyebrow {{ color:#487183;font-size:11px;font-weight:750;letter-spacing:1.7px;text-transform:uppercase; }}
header {{ display:flex;justify-content:space-between;align-items:center;gap:20px; }}
h1 {{ margin:9px 0;font-size:36px;letter-spacing:-1px; }}
header p {{ color:#58717f;font-size:13px;margin:0;line-height:1.6; }}
.badge {{ background:#deeee9;color:#08674f;border:1px solid #b9dcd0;padding:10px 14px;
font-size:11px;font-weight:750;border-radius:6px;white-space:nowrap; }}
.metrics {{ display:grid;grid-template-columns:repeat({len(metrics)},1fr);gap:15px;margin:25px 0 20px; }}
.metric,.panel {{ background:white;border:1px solid #dce5eb;border-radius:9px;overflow:hidden; }}
.metric {{ padding:17px 21px;border-top:3px solid #278e79; }}
.metric strong {{ display:block;font-size:31px;color:#164b55; }}
.metric span {{ display:block;font-size:13px;font-weight:650;margin:6px 0; }}
.metric small {{ color:#667e8c;font-size:11px; }}
.panel {{ margin-bottom:20px; }} .panel-title {{ padding:16px 20px;border-bottom:1px solid #e8edf0; }}
h2 {{ font-size:17px;margin:0 0 5px;letter-spacing:-.2px; }} .panel-title p {{ font-size:11px;color:#637c8b;margin:0; }}
.tables {{ display:grid;grid-template-columns:1.15fr 1fr;gap:20px;align-items:start; }}
.scroll {{ overflow:auto; }} table {{ width:100%;border-collapse:collapse;text-align:left;font-size:12px; }}
th {{ padding:11px 18px;background:#f8fafb;color:#5b7382;font-size:9px;text-transform:uppercase;letter-spacing:.6px; }}
td {{ padding:10px 18px;border-top:1px solid #edf1f3;font-variant-numeric:tabular-nums;white-space:nowrap; }}
.ok {{ color:#087456; }} .warn {{ color:#a76320; }} b.ok,b.warn {{ font-size:10px;letter-spacing:.5px; }}
details {{ font-size:12px; }} summary {{ padding:14px 20px;cursor:pointer;font-weight:650; }}
.note {{ font-size:10px;color:#637c8b;line-height:1.7; }} .note p {{ margin:5px 0; }}
code {{ font-family:ui-monospace,monospace; }} a {{ color:#236b8a; }}
@media(max-width:900px) {{ main {{ padding:22px; }} .metrics {{ grid-template-columns:1fr 1fr; }}
.tables {{ grid-template-columns:1fr; }} h1 {{ font-size:29px; }} header {{ display:block; }}
.badge {{ display:inline-block;margin-top:14px; }} }}
</style></head><body><main><header><div><div class="eyebrow">Local Delta Lake / Result evidence</div>
<h1>{title}</h1><p>{subtitle}</p></div><span class="badge">ACTUAL TABLE SNAPSHOTS</span></header>
<section class="metrics">{cards}</section>{comparison}<section class="tables">{"".join(panels)}</section>
{"".join(additional)}
<details class="panel"><summary>Snapshot inventory · all {len(tables)} tables</summary>{inventory}</details>
<footer class="note"><p>{note} Full rows and check differences: <a href="tables.json">tables.json</a>.</p>
<p>Source: <code>{html.escape(snapshot["source"])}</code> · Exported {snapshot["exported_at_utc"]}.</p>
<p>{html.escape(runtime)}. Read-only export; table versions are captured individually,
without a cross-table transaction.
Stop writers before refreshing evidence. Demo data is synthetic.</p></footer></main></body></html>
"""


def export_report(root: Path, output: Path, repair_version: int = 2, race_version: int = 3) -> dict[str, Any]:
    """Read and validate before writing report artifacts; preserve other output files."""
    source = root.resolve()
    destination = output.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Report output must be outside the source lake")
    snapshot = inspect_lake(root, repair_version, race_version)
    document = render_report(snapshot)
    output.mkdir(parents=True, exist_ok=True)
    (output / "tables.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(document, encoding="utf-8")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake", type=Path, default=Path("lake"), help="Existing Delta lake; never recreated")
    parser.add_argument("--output", type=Path, default=Path("docs/results"), help="HTML and JSON destination")
    parser.add_argument("--repair-version", type=int, default=2, help="Silver reference for repair comparisons")
    parser.add_argument("--race-version", type=int, default=3, help="Silver reference for release replays")
    args = parser.parse_args()
    if min(args.repair_version, args.race_version) < 0:
        parser.error("Reference versions must be nonnegative")
    try:
        export_report(args.lake, args.output, args.repair_version, args.race_version)
    except (DeltaError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Cannot inspect lake at {args.lake}: {exc}\nRun the demo or choose an existing lake.\n")
    print(f"Exported actual Delta snapshots to {args.output / 'index.html'} and {args.output / 'tables.json'}")


if __name__ == "__main__":
    main()
