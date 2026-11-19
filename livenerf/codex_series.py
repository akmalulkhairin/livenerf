import argparse
import asyncio
import fcntl
import json
import os
import subprocess
from datetime import date, datetime, timezone

from inspect_ai import eval

from .benchmarks import tasks
from .benchmarks.data import LOADERS
from .codex_budget import BudgetStop, check_account, daily_capacity, reserve
from .codex_calibrate import PREFLIGHT_RESERVATION, read_limits, restore_aime_2026, study_id
from .codex_panel import read_panel, verified_items
from .codex_publish import publish_design
from .codex_validate import ARMS, validation_result, validation_rows
from .providers.codex.instrument import CLI_VERSION, STUDY_HOME, InstrumentError, check_version


def ready_panel(root, pool):
    panel, digest = read_panel(root)
    families = verified_items(panel, pool)
    if panel["samples_per_item_per_day"] != 1:
        raise ValueError("The frozen protocol requires one sample per item per UTC day")
    validation = validation_result(panel, validation_rows(root, panel, digest))
    if not validation["passed"]:
        raise ValueError("The frozen panel has not passed instrument validation")
    return panel, digest, families


def pending_samples(directory, panel):
    return [(arm, item) for arm, key in (("measured", "panel"), ("control", "control"))
            for item in panel[key] if not (directory / arm / item).exists()]


def run_day(root, day, panel, digest, families):
    directory = root / "series" / day
    pending = pending_samples(directory, panel)
    if not pending:
        print(f"{day}: all {len(panel['panel']) + len(panel['control'])} sample attempts already recorded.")
        return

    check_version()
    budget = STUDY_HOME.parent / "study-budget.json"
    if not directory.exists():
        limits = asyncio.run(read_limits())
        if datetime.now(timezone.utc).date().isoformat() != day:
            raise BudgetStop("The UTC day ended before the panel started")
        upcoming_points = 0
        if not directory.parent.exists() or not any(path.is_dir() for path in directory.parent.iterdir()):
            _, reset = check_account(limits)
            last_day = datetime.fromtimestamp(reset - 1, timezone.utc).date()
            upcoming_points = (last_day - date.fromisoformat(day)).days * PREFLIGHT_RESERVATION
        reserve(budget, limits, PREFLIGHT_RESERVATION, upcoming_points=upcoming_points)
        directory.mkdir(parents=True)

    task_by_family = {}
    for arm, item in pending:
        if datetime.now(timezone.utc).date().isoformat() != day:
            raise BudgetStop("The UTC day ended before the panel finished")
        reserve(budget, asyncio.run(read_limits()), 0)
        family = families[item]
        if family not in task_by_family:
            task_by_family[family] = getattr(tasks, family)(panel="all")
        model, effort = ARMS["high" if arm == "measured" else "control"]
        if datetime.now(timezone.utc).date().isoformat() != day:
            raise BudgetStop("The UTC day ended before the panel finished")
        attempt = directory / arm / item
        attempt.mkdir(parents=True)
        eval(
            task_by_family[family], model=f"codex-study/{model}", effort=effort,
            log_dir=str(attempt), sample_id=[item], max_connections=1, max_retries=0,
            metadata={"study_id": root.name, "panel_sha256": digest, "arm": arm,
                      "harness_sha": f"codex-study+{root.name}", "cli_version": CLI_VERSION},
            tags=["livenerf-codex", "series", arm], display="none",
        )


def main():
    parser = argparse.ArgumentParser(description="Check the Codex drift series or collect today's frozen panel.")
    parser.add_argument("--run", action="store_true", help="Run the validated panel subject to quota")
    args = parser.parse_args()
    os.umask(0o077)
    root = STUDY_HOME.parent / "study" / study_id()
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        if not (root / "panel").exists():
            raise ValueError("Screening and confirmation must finish before the panel can be frozen")
        restore_aime_2026()
        panel, digest, families = ready_panel(root, {family: loader() for family, loader in LOADERS.items()})
        directory = root / "series" / day
        capacity = daily_capacity(PREFLIGHT_RESERVATION)
        print(json.dumps({
            "study_id": root.name, "panel_sha256": digest, "utc_day": day,
            "astra_items": len(panel["panel"]), "sol_items": len(panel["control"]),
            "pending": len(pending_samples(directory, panel)),
            "capacity": capacity,
        }))
        if args.run:
            if not capacity["supports_daily_series"]:
                raise BudgetStop("The weekly reservation policy cannot sustain the daily series")
            with (STUDY_HOME.parent / ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                publish_design(root)
                run_day(root, day, panel, digest, families)
    except (BudgetStop, BlockingIOError) as stop:
        print(f"Series paused: {stop}")
    except (InstrumentError, OSError, TimeoutError, KeyError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Series stopped: {error}\n")


if __name__ == "__main__":
    main()
