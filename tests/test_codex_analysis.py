import math

import pandas as pd

from livenerf.codex_analysis import attribute, window_decisions
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
