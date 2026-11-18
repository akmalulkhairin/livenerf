import math

import pandas as pd

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
