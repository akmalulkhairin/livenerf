import math

import pandas as pd
import pytest

from livenerf import codex_analysis
from livenerf.codex_analysis import attribute, window_decisions, write_formal_report
from livenerf.providers.codex.instrument import CLI_VERSION


def test_drift_keeps_missing_windows_and_excludes_open_window():
    start = pd.Timestamp("2026-11-18", tz="UTC")

    def window(offset, delta=math.nan):
        return {
            "window": f"{start + pd.Timedelta(days=offset):%Y-%m-%d} +10d",
            "samples": 20, "errors": 0, "cli_versions": CLI_VERSION, "harness_hashes": "frozen",
            "delta_vs_baseline": delta, "delta_se": 0.01,
        }

    summary = pd.DataFrame([window(0), window(10, -0.05), window(30, -0.05), window(40, -0.05)])
    closed = window_decisions(summary, start, start + pd.Timedelta(days=45), 2, "frozen")
    assert len(closed) == 4
    assert closed[1]["qualifies"]
    assert closed[2]["missing"] == 20
    assert closed[3]["qualifies"] and not closed[3]["change_declared"]

    sustained = pd.DataFrame([window(0), window(10, -0.05), window(20, -0.05)])
    astra = window_decisions(sustained, start, start + pd.Timedelta(days=30), 2, "frozen")
    assert astra[-1]["change_declared"]
    assert attribute(astra, astra)[-1]["outcome"] == "shared-shift"

    sustained.loc[2, "samples"] = 19
    sol_gap = window_decisions(sustained, start, start + pd.Timedelta(days=30), 2, "frozen")
    assert attribute(astra, sol_gap)[-1]["outcome"] == "control-inconclusive"


def test_formal_chart_keeps_the_utc_baseline_and_missing_control(tmp_path):
    result = {
        "stage": "series",
        "series_started": "2026-11-18T00:00:00+00:00",
        "baseline_ends": "2026-11-28T00:00:00+00:00",
        "panel_sizes": {"measured": 5, "control": 2},
        "daily": {
            "measured": [{"day": "2026-11-18", "score": 0.8, "se": 0.12, "samples": 5, "errors": 0, "missing": 0}],
            "control": [{"day": "2026-11-20", "score": 0.5, "se": 0.25, "samples": 2, "errors": 0, "missing": 0}],
        },
        "windows": {
            "measured": [{"covered": True, "score": 0.65}],
            "control": [{"covered": False, "score": 0.5}],
        },
    }
    write_formal_report(tmp_path, result)
    report = tmp_path / "reports"
    chart = (report / "daily-dark.svg").read_text()
    assert "Astra baseline 65.0%" in chart
    assert chart.count("stroke-dasharray") == 1
    assert chart.count("<circle") == 2
    assert "Baseline coverage is incomplete" in chart
    assert "2026-11-19,gpt-6.2-sol,,,0,0,2" in (report / "daily.csv").read_text()


def test_upstream_drift_rejects_missing_cli_in_one_of_several_records(tmp_path, monkeypatch):
    start = pd.Timestamp("2026-11-18", tz="UTC")
    (tmp_path / "series" / "2026-11-18").mkdir(parents=True)
    panel = {"upstream_revision": "upstream", "panel": ["a", "b"], "control": ["a", "b"],
             "item_hashes": {"a": "hash-a", "b": "hash-b"}}
    rows = [
        {"arm": "measured", "study_id": tmp_path.name, "panel_sha256": "digest", "effort": "high",
         "model": "codex-study/gpt-6.2-astra", "id": item, "item_hash": f"hash-{item}",
         "harness_sha": f"codex-study+{tmp_path.name}", "cli_version": cli, "score": 1, "error": None,
         "run_created": start, "run_status": "success", "scheduled_utc_day": "2026-11-18",
         "attempt_path": ("2026-11-18", "measured", item)}
        for item, cli in (("a", CLI_VERSION), ("b", None))
    ]
    monkeypatch.setattr(codex_analysis, "read_panel", lambda root: (panel, "digest"))
    monkeypatch.setattr(codex_analysis, "load_samples", lambda directory: pd.DataFrame(rows))
    with pytest.raises(ValueError, match="lacks the pinned CLI"):
        codex_analysis.report(tmp_path, start)


def test_attempt_starting_after_midnight_is_an_error_on_its_scheduled_day():
    rows = pd.DataFrame([
        {"id": "a", "scheduled_utc_day": day, "attempt_path": (day, "control", "a"),
         "run_created": pd.Timestamp("2026-11-19 00:01:00", tz="UTC"), "run_status": "success",
         "error": None, "score": 1}
        for day in ("2026-11-18", "2026-11-19")
    ])
    checked = codex_analysis.scheduled_records(rows, ["2026-11-18", "2026-11-19"], "control")
    assert list(checked["run_created"].dt.strftime("%Y-%m-%d")) == ["2026-11-18", "2026-11-19"]
    assert checked["error"].notna().tolist() == [True, False]
    assert checked["score"].isna().tolist() == [True, False]
