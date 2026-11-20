import asyncio
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

from .codex_budget import BudgetStop, usage_percent
from .codex_calibrate import read_limits
from .codex_upstream_study import upstream_study_id
from .providers.codex.instrument import STUDY_HOME, InstrumentError


def series_attempts(root):
    return Counter(path.parents[2].name for path in (root / "series").glob("*/*/*/*.eval"))


def meter_reading():
    try:
        weekly = asyncio.run(read_limits())["primary"]
        if weekly["windowDurationMins"] != 10080 or type(weekly["resetsAt"]) is not int:
            raise ValueError("Codex did not return a weekly quota window")
        return {
            "utc": datetime.now(timezone.utc).isoformat(),
            "used_percent": usage_percent(weekly),
            "resets_at": weekly["resetsAt"],
        }
    except (BudgetStop, InstrumentError, OSError, TimeoutError, KeyError, TypeError, ValueError):
        print("Could not read the weekly account meter for this invocation.", file=sys.stderr, flush=True)
        return None


def run_with_meter(root):
    try:
        attempts_before = series_attempts(root)
        meter_before = meter_reading()
    except OSError:
        attempts_before = None
        print("Could not count existing series attempts.", file=sys.stderr, flush=True)

    result = subprocess.run([sys.executable, "-m", "livenerf.codex_upstream_study", "--run"])

    if attempts_before is not None:
        try:
            new_attempts = series_attempts(root) - attempts_before
            if new_attempts:
                record = {"utc_days": dict(new_attempts), "before": meter_before,
                          "after": meter_reading(), "exit_status": result.returncode}
                with (root / "quota-readings.jsonl").open("a") as log:
                    log.write(json.dumps(record) + "\n")
        except OSError:
            print("Could not save the series quota readings.", file=sys.stderr, flush=True)

    return result.returncode


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(run_with_meter(STUDY_HOME.parent / "study" / upstream_study_id()))
