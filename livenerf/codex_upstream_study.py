import argparse
import fcntl
import hashlib
import json
import math
import os
import subprocess

import pandas as pd

from .codex_analysis import report, write_formal_report
from .codex_budget import BudgetStop, daily_capacity
from .codex_calibrate import PREFLIGHT_RESERVATION, restore_aime_2026
from .codex_comparison import UPSTREAM_COMMIT, comparison_id, upstream_panel
from .codex_panel import freeze_panel, read_panel
from .codex_publish import publish, publish_design
from .codex_series import run_day
from .codex_validate import ARMS, REPS, pending_pairs, run_batch, validation_result, validation_rows
from .common import REPO_ROOT
from .design import daily_sensitivity
from .providers.codex.instrument import CLI_VERSION, STUDY_HOME, InstrumentError


def study_design():
    panel, families = upstream_panel()
    sensitivity = daily_sensitivity([{"p": 0.5}] * len(panel["panel"]))
    return {
        **panel,
        "stage": "panel-candidate",
        "upstream_revision": UPSTREAM_COMMIT,
        "samples_per_item_per_day": 1,
        "predicted_sensitivity": {**sensitivity, "equal_panel_for_both_models": True, "assumed_pass_rate": 0.5},
    }, families


def upstream_study_id():
    digest = hashlib.sha256(f"codex-drift-v1\0{comparison_id()}\0{ARMS}\0{REPS}".encode())
    for module in ("codex_upstream_study.py", "codex_series.py", "codex_validate.py",
                   "codex_analysis.py", "analysis/__init__.py"):
        digest.update(hashlib.sha256((REPO_ROOT / "livenerf" / module).read_bytes()).digest())
    return digest.hexdigest()[:16]


def json_numbers(value):
    if isinstance(value, dict):
        return {key: json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_numbers(item) for item in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def advance_study(root, panel, digest, families):
    rows = validation_rows(root, panel, digest)
    pending = pending_pairs(panel, rows)
    if pending:
        publish_design(root)
        run_batch(root, panel, digest, families, len(panel["panel"]) + len(panel["control"]), task_panel="daily")
        rows = validation_rows(root, panel, digest)
    validation = json_numbers(validation_result(panel, rows))
    print(json.dumps(validation, allow_nan=False), flush=True)
    if validation["pending_pairs"]:
        return

    receipt = (json.dumps({
        "study_id": root.name, "panel_sha256": digest, "cli_version": CLI_VERSION, "arms": ARMS,
        "replicates_per_question_and_arm": REPS, "validation": validation,
        "last_sample_started": max((row["created"] for row in rows), default=None),
    }, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    publish_design(root, validation=receipt)
    if not validation["passed"] or pending:
        return
    if not daily_capacity(PREFLIGHT_RESERVATION)["supports_daily_series"]:
        raise BudgetStop("The weekly reservation policy cannot sustain the daily series")
    day = pd.Timestamp.now(tz="UTC").date().isoformat()
    try:
        run_day(root, day, panel, digest, families, task_panel="daily")
    except BudgetStop as stop:
        print(f"Series paused: {stop}", flush=True)
    output = write_formal_report(root, report(root, pd.Timestamp.now(tz="UTC")))
    if output:
        publish(output, study=root.name)


def main():
    parser = argparse.ArgumentParser(description="Validate and run the Codex drift study on LiveNerf's fixed panel.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Freeze and publish the design without sampling")
    mode.add_argument("--run", action="store_true", help="Advance validation or collect the current UTC day")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        restore_aime_2026()
        design, families = study_design()
        identity = upstream_study_id()
        state = STUDY_HOME.parent
        root = state / "study" / identity
        print(f"Upstream-panel drift study {identity}. {len(families)} questions per model.", flush=True)
        if not (args.prepare or args.run):
            if (root / "panel").exists():
                panel, digest = read_panel(root)
                print(json.dumps(json_numbers(validation_result(panel, validation_rows(root, panel, digest))),
                                 allow_nan=False))
            return
        state.mkdir(parents=True, exist_ok=True)
        with (state / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            digest = freeze_panel(root, design)
            panel, _ = read_panel(root)
            if args.prepare:
                publish_design(root)
                return
            advance_study(root, panel, digest, families)
    except (BudgetStop, BlockingIOError) as stop:
        print(f"Study paused: {stop}", flush=True)
    except (InstrumentError, OSError, TimeoutError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Study stopped: {error}\n")


if __name__ == "__main__":
    main()
