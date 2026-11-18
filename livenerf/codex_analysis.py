import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from .analysis import BASELINE_HOURS, MAX_ERROR_RATE, WINDOW_DAYS, decision, load_samples, realized_mde, summarize
from .codex_calibrate import study_id
from .codex_panel import read_panel
from .codex_report import DailyEstimate, StudyBaseline, write_charts
from .codex_validate import ARMS
from .providers.codex.instrument import CLI_VERSION, STUDY_HOME


def window_decisions(summary, start, now, items, harness):
    days = WINDOW_DAYS["F"]
    stride = pd.Timedelta(days=days)
    closed = (now.floor("D") - start) // stride
    labels = [f"{start + number * stride:%Y-%m-%d} +{days}d" for number in range(closed)]
    if not labels:
        return []
    actual = summary.set_index("window").to_dict(orient="index") if not summary.empty else {}
    windows = []
    for label in labels:
        row = actual.get(label, {})
        samples = int(row.get("samples", 0))
        expected = items * days
        if samples > expected:
            raise ValueError("More samples were recorded than scheduled in a window")
        missing = expected - samples
        errors = int(row.get("errors", 0))
        covered = (
            (errors + missing) / expected < MAX_ERROR_RATE
            and row.get("cli_versions") == CLI_VERSION and row.get("harness_hashes") == harness
        )
        delta = row.get("delta_vs_baseline", math.nan)
        se = row.get("delta_se", math.nan)
        windows.append({
            "window": label, "expected": expected, "samples": samples, "errors": errors, "missing": missing,
            "covered": covered, "cli_versions": row.get("cli_versions", ""),
            "harness_hashes": row.get("harness_hashes", ""),
            "delta": delta if math.isfinite(delta) else None, "se": se if math.isfinite(se) else None,
            "score": finite(row.get("score")),
        })

    baseline_covered = windows[0]["covered"]
    rows = [{
        **row,
        "delta_vs_baseline": (math.nan if index == 0 else
                              row["delta"] if row["delta"] is not None and baseline_covered and row["covered"] else 0),
        "delta_se": row["se"] if baseline_covered and row["covered"] and row["se"] is not None else math.nan,
    } for index, row in enumerate(windows)]
    by_window = {row["window"]: row for row in decision(pd.DataFrame(rows))}
    for row in windows:
        rule = by_window.get(row["window"], {})
        row.update(qualifies=rule.get("qualifies", False), change_declared=rule.get("change_declared", False))
    return windows


def finite(value):
    return value if value is not None and math.isfinite(value) else None


def attribute(measured, control):
    results = []
    for index, (primary, comparator) in enumerate(zip(measured, control, strict=True)):
        outcome = "no-change-declared"
        if primary["change_declared"]:
            control_ready = index > 0 and control[0]["covered"] and all(
                row["covered"] and row["se"] is not None for row in control[index - 1:index + 1]
            )
            if not control_ready:
                outcome = "control-inconclusive"
            elif comparator["change_declared"] and (comparator["delta"] > 0) == (primary["delta"] > 0):
                outcome = "shared-shift"
            else:
                outcome = "astra-shift-without-matching-sol-shift"
        results.append({"window": primary["window"], "outcome": outcome})
    return results


def report(root, now):
    panel, digest = read_panel(root)
    directory = root / "series"
    dates = sorted(path.name for path in directory.iterdir() if path.is_dir()) if directory.exists() else []
    if not dates:
        return {"stage": "awaiting-series", "panel_sha256": digest}
    start = pd.Timestamp(dates[0], tz="UTC")
    cutoff = start + pd.Timedelta(hours=BASELINE_HOURS)
    data = load_samples(str(directory))
    if not data.empty and not data["arm"].isin({"measured", "control"}).all():
        raise ValueError("The series contains an unrecognised arm")
    windows = {}
    sensitivity = {}
    daily = {}
    panel_sizes = {}
    for arm, model_key, panel_key in (("measured", "high", "panel"), ("control", "control", "control")):
        records = data[data["arm"] == arm] if not data.empty else data
        ids = set(panel[panel_key])
        panel_sizes[arm] = len(ids)
        if not records.empty:
            if (
                not records["study_id"].eq(root.name).all()
                or not records["panel_sha256"].eq(digest).all()
                or not records["model"].eq(f"codex-study/{ARMS[model_key][0]}").all()
                or not records["id"].isin(ids).all()
                or not records["item_hash"].eq(records["id"].map(panel["item_hashes"])).all()
            ):
                raise ValueError("A series record does not match its frozen panel and model")
            key = records.assign(day=records["run_created"].dt.floor("D"))[["day", "id"]]
            if key.duplicated().any() or (key["day"] < start).any():
                raise ValueError("Series records contain duplicate attempts or precede the study")
        summary = summarize(records, baseline_end=cutoff, freq="F", series_start=start) if not records.empty else records
        windows[arm] = window_decisions(summary, start, now, len(ids), root.name)
        daily[arm] = [
            {"day": row.window, "score": finite(row.score), "se": finite(row.score_se),
             "samples": int(row.samples), "errors": int(row.errors), "missing": len(ids) - int(row.samples)}
            for row in summarize(records, baseline_end=cutoff, series_start=start).itertuples()
        ] if not records.empty else []
        if windows[arm] and windows[arm][0]["covered"]:
            baseline = records[(records["run_created"] < cutoff) & records["error"].isna()]
            sensitivity[arm] = {key: value for key, value in realized_mde(baseline).items()
                                if math.isfinite(value)}

    return {
        "stage": "series", "panel_sha256": digest, "series_started": start.isoformat(),
        "baseline_ends": cutoff.isoformat(), "panel_sizes": panel_sizes, "daily": daily,
        "baseline_sensitivity": sensitivity, "windows": windows,
        "decisions": attribute(windows["measured"], windows["control"]),
    }


def write_formal_report(root, result):
    if result["stage"] != "series" or not any(result["daily"].values()):
        return
    out = root / "reports"
    out.mkdir(exist_ok=True)
    model_by_arm = {"measured": ARMS["high"][0], "control": ARMS["control"][0]}
    daily = {arm: {row["day"]: row for row in rows} for arm, rows in result["daily"].items()}
    start = pd.Timestamp(result["series_started"])
    cutoff = pd.Timestamp(result["baseline_ends"])
    last = max(day for rows in daily.values() for day in rows)
    rows = []
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=out, delete=False) as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(("utc_day", "model", "score", "standard_error", "samples", "errors", "missing"))
        for day in pd.date_range(start, pd.Timestamp(last, tz="UTC")):
            iso = day.date().isoformat()
            values = {}
            for arm, model in model_by_arm.items():
                row = daily[arm].get(iso)
                if row is None:
                    writer.writerow((iso, model, None, None, 0, 0, result["panel_sizes"][arm]))
                    continue
                writer.writerow((iso, model, *(row[key] for key in ("score", "se", "samples", "errors", "missing"))))
                if row["score"] is not None:
                    values[model] = DailyEstimate(row["score"], row["se"] if row["se"] is not None else math.nan)
            rows.append((day.date(), values))
    Path(file.name).replace(out / "daily.csv")

    means = {
        model_by_arm[arm]: windows[0]["score"] for arm, windows in result["windows"].items()
        if windows and windows[0]["covered"] and windows[0]["score"] is not None
    }
    status = ""
    if not result["windows"]["measured"]:
        status = f"Collecting the UTC baseline · closes {cutoff:%b %d}"
    elif len(means) != len(model_by_arm):
        status = "Baseline coverage is incomplete"
    baseline = StudyBaseline((cutoff - pd.Timedelta(days=1)).date(), means, status)
    write_charts(out, rows, tuple(model_by_arm.values()), study_baseline=baseline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyse the validated Codex drift series.")
    parser.add_argument("--write", action="store_true", help="Write local daily charts and aggregate CSV")
    args = parser.parse_args()
    root = STUDY_HOME.parent / "study" / study_id()
    if not (root / "panel").exists():
        raise SystemExit("The study has no frozen panel yet.")
    result = report(root, pd.Timestamp(datetime.now(timezone.utc)))
    if args.write:
        write_formal_report(root, result)
    print(json.dumps(result, allow_nan=False, indent=2))
