import json
import math
from datetime import datetime, timezone

import pandas as pd

from .analysis import BASELINE_HOURS, MAX_ERROR_RATE, WINDOW_DAYS, decision, load_samples, realized_mde, summarize
from .codex_calibrate import study_id
from .codex_panel import read_panel
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
    for arm, model_key, panel_key in (("measured", "high", "panel"), ("control", "control", "control")):
        records = data[data["arm"] == arm] if not data.empty else data
        ids = set(panel[panel_key])
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
        if windows[arm] and windows[arm][0]["covered"]:
            baseline = records[(records["run_created"] < cutoff) & records["error"].isna()]
            sensitivity[arm] = {key: value for key, value in realized_mde(baseline).items()
                                if math.isfinite(value)}

    return {
        "stage": "series", "panel_sha256": digest, "baseline_ends": cutoff.isoformat(),
        "baseline_sensitivity": sensitivity, "windows": windows,
        "decisions": attribute(windows["measured"], windows["control"]),
    }


if __name__ == "__main__":
    root = STUDY_HOME.parent / "study" / study_id()
    if not (root / "panel").exists():
        raise SystemExit("The study has no frozen panel yet.")
    print(json.dumps(report(root, pd.Timestamp(datetime.now(timezone.utc))), allow_nan=False, indent=2))
