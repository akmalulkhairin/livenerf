import argparse
import asyncio
import fcntl
import hashlib
import io
import json
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
from inspect_ai import eval

from .benchmarks import calibrate, tasks
from .benchmarks.data import AIME_SHA256, LOADERS, _aime_norm, cache_dir
from .codex_budget import WEEKLY_POINTS, BudgetStop, check_account, reserve, usage_percent
from .common import REPO_ROOT
from .providers.codex.instrument import CLI_VERSION, MODEL, STUDY_HOME, InstrumentError, app_server, check_version

AIME_2026_REVISION = "d2de22f3c656b4f56cf8981212186377d1e23bc3"
STUDY_EFFORT = "high"
PREFLIGHT_RESERVATION = 2
MEASUREMENT_SAMPLES = 64
SCREENING_BATCH_SAMPLES = 128
MEASURED_SCREENING_FAMILIES = {"gpqa", "mmlupro"}
METER_SIGNAL = 3


def restore_aime_2026():
    path = cache_dir() / "aime_2026.json"
    if path.exists():
        return
    url = f"https://huggingface.co/datasets/MathArena/aime_2026/resolve/{AIME_2026_REVISION}/data/train-00000-of-00001.parquet"
    with urllib.request.urlopen(url, timeout=30) as response:
        rows = pd.read_parquet(io.BytesIO(response.read())).to_dict("records")
    if hashlib.sha256(_aime_norm(rows).encode()).hexdigest() != AIME_SHA256[2026]:
        raise ValueError("Historical AIME 2026 revision differs from the upstream digest")
    with path.open("x") as file:
        json.dump({"rows": [{"row": row} for row in rows]}, file)


def study_id():
    files = (
        "uv.lock", "prompts/system_v1.txt", "livenerf/common.py",
        "livenerf/providers/codex/instrument.py", "livenerf/benchmarks/calibrate.py",
        "livenerf/benchmarks/tasks.py", "livenerf/benchmarks/data.py",
        "livenerf/scorers/__init__.py", "livenerf/scorers/checks.py",
    )
    digest = hashlib.sha256()
    digest.update(f"{MODEL}\0{CLI_VERSION}\0{STUDY_EFFORT}\0".encode())
    for name in files:
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256((REPO_ROOT / name).read_bytes()).digest())
    return digest.hexdigest()[:16]


def next_batch(pool, screen, confirmation, stage, size):
    first, repeats = [], []
    for family, items in pool.items():
        for item in items:
            item_id = item["id"]
            current = screen[item_id] if stage == "screen" else confirmation[item_id]
            wanted = (calibrate.screen_wanted(current) if stage == "screen"
                      else calibrate.confirm_wanted(screen[item_id], current))
            if wanted:
                (first if not current["scores"] else repeats).append((family, item_id))
    return (first or repeats)[:size]


def scheduled_items(pending, stage):
    if stage == "screen" and pending:
        family = pending[0][0]
        if family in MEASURED_SCREENING_FAMILIES:
            return [sample for sample in pending if sample[0] == family]
    return pending[:calibrate.CHUNK]


async def read_limits():
    async with asyncio.timeout(20), app_server() as (server, _):
        return (await server.request("account/rateLimits/read", {}))["rateLimits"]


def measurement_window(root, limits, size):
    used, reset = check_account(limits)
    checkpoint = root / "measurement.json"
    if checkpoint.exists():
        window = json.loads(checkpoint.read_text())
    else:
        path = root / "batches.jsonl"
        previous = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        previous = [batch for batch in previous if batch.get("mode") == "measurement"]
        window = {"start": previous[0]["weekly_before"] if previous else used,
                  "reset": previous[0]["weekly_reset"] if previous else reset,
                  "attempts": sum(batch["attempts"] for batch in previous)}
    if window["attempts"] >= size:
        raise BudgetStop("The one-off measurement has reached its sample limit")
    check_measurement(limits, window["start"], window["reset"])
    return window


def record_measurement_attempt(root, window):
    window["attempts"] += 1
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as file:
        json.dump(window, file)
    Path(file.name).replace(root / "measurement.json")


def check_measurement(limits, starting_usage, reset):
    used, _ = check_account(limits)
    if time.time() >= reset or used < starting_usage:
        raise BudgetStop("The original measurement window is no longer current")
    if used - starting_usage >= METER_SIGNAL:
        raise BudgetStop(f"The weekly meter moved by at least {METER_SIGNAL} points")


def collect_batch(root, pool, size, *, measure=False, screen_family=None, weekly_points=WEEKLY_POINTS):
    screen = calibrate.history(root / "screen")
    confirmation = calibrate.history(root / "confirmation")
    stage = "screen"
    if screen_family:
        pool = {screen_family: pool[screen_family]}
    pending = next_batch(pool, screen, confirmation, stage, size)
    if not pending and not screen_family:
        stage = "confirmation"
        pending = next_batch(pool, screen, confirmation, stage, size)
    if not pending:
        print(f"{screen_family} screening is complete." if screen_family else "Screening and confirmation are complete.")
        return

    budget = STUDY_HOME.parent / "study-budget.json"
    limits = asyncio.run(read_limits())
    started_at = datetime.now(timezone.utc).isoformat()
    batch_start_usage = usage_percent(limits["primary"])
    if measure:
        window = measurement_window(root, limits, size)
        used, weekly_reset = window["start"], window["reset"]
        pending = pending[:size - window["attempts"]]
        print(f"{stage}: measuring usage over up to {len(pending)} samples. Weekly meter {used}%.", flush=True)
    else:
        if not screen_family:
            pending = scheduled_items(pending, stage)
        used, points = reserve(budget, limits, PREFLIGHT_RESERVATION, weekly_points=weekly_points)
        weekly_reset = limits["primary"]["resetsAt"]
        print(f"{stage}: up to {len(pending)} samples. Weekly meter {used}%, study points reserved {points}.", flush=True)
    completed = 0
    input_units = 0
    cached_input_units = 0
    output_tokens = 0
    scored = 0
    attempts_by_family = Counter()
    scores_by_family = Counter()
    task_by_family = {}
    try:
        for family, item_id in pending:
            limits = asyncio.run(read_limits())
            if measure:
                check_measurement(limits, used, weekly_reset)
                record_measurement_attempt(root, window)
            else:
                if screen_family and time.time() >= weekly_reset:
                    raise BudgetStop("The authorised screening window ended")
                reserve(budget, limits, 0, weekly_points=weekly_points)
            if family not in task_by_family:
                task_by_family[family] = getattr(tasks, family)(panel="all")
            attempts_by_family[family] += 1
            (log,) = eval(
                task_by_family[family], model=f"codex-study/{MODEL}", effort=STUDY_EFFORT,
                sample_id=[item_id], log_dir=str(root / stage), max_connections=1, max_retries=0,
                display="none", tags=["livenerf-codex", "calibration", stage],
                metadata={"study_id": root.name},
            )
            completed += 1
            sample_scores = sum(not sample.error and bool(sample.scores) for sample in (log.samples or ()))
            scores_by_family[family] += sample_scores
            scored += sample_scores
            for usage in log.stats.model_usage.values():
                input_units += usage.input_tokens
                cached_input_units += usage.input_tokens_cache_read or 0
                output_tokens += usage.output_tokens
            print(f"{stage}: {completed}/{len(pending)} attempted, {scored} scored.", flush=True)
    finally:
        try:
            final = asyncio.run(read_limits())["primary"]
            weekly_after = usage_percent(final) if time.time() < weekly_reset else None
        except (InstrumentError, BudgetStop, TimeoutError, OSError, KeyError, ValueError):
            weekly_after = None
        with (root / "batches.jsonl").open("a") as file:
            file.write(json.dumps({
                "utc": datetime.now(timezone.utc).isoformat(), "stage": stage, "weekly_before": used,
                "mode": "measurement" if measure else "manual-screen" if screen_family else "scheduled",
                "weekly_cap_points": weekly_points if not measure else None,
                "weekly_after": weekly_after, "weekly_reset": weekly_reset,
                "started_at": started_at, "weekly_batch_before": batch_start_usage,
                "attempts_by_family": dict(attempts_by_family), "scored_by_family": dict(scores_by_family),
                "attempts": completed, "scored": scored, "output_tokens": output_tokens,
                "input_tokens": input_units, "cached_input_tokens": cached_input_units,
            }) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Check the pinned Codex calibration pool or collect a batch.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--one", action="store_const", dest="size", const=1, help="Collect one sample")
    mode.add_argument("--batch", type=int, dest="size", metavar="SIZE", help="Collect a budgeted calibration batch")
    mode.add_argument("--measure", action="store_true", help="Run a bounded usage measurement with the account stop")
    parser.add_argument("--screen-family", choices=LOADERS, help="Screen only this family in a manual batch")
    parser.add_argument("--weekly-points", type=int, help="Use an explicitly authorised manual screening allowance")
    args = parser.parse_args()
    batch_limit = SCREENING_BATCH_SAMPLES
    if args.screen_family and args.screen_family not in MEASURED_SCREENING_FAMILIES:
        batch_limit = MEASUREMENT_SAMPLES
    if args.size is not None and not 1 <= args.size <= batch_limit:
        parser.error(f"Batch size must be between 1 and {batch_limit}.")
    if args.screen_family and args.size is None:
        parser.error("Manual family screening requires an explicit batch size.")
    if args.weekly_points is not None and (
        not args.screen_family or args.weekly_points < WEEKLY_POINTS
    ):
        parser.error(f"--weekly-points requires --screen-family and at least {WEEKLY_POINTS} study points.")
    os.umask(0o077)
    try:
        restore_aime_2026()
        pool = {family: loader() for family, loader in LOADERS.items()}
        for family, items in pool.items():
            print(f"{family}: {len(items)} questions verified", flush=True)
        root = STUDY_HOME.parent / "study" / study_id()
        print(f"Study {root.name}", flush=True)
        if args.size is None and not args.measure:
            return
        check_version()
        with (STUDY_HOME.parent / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            root.mkdir(parents=True, exist_ok=True)
            collect_batch(
                root, pool, MEASUREMENT_SAMPLES if args.measure else args.size, measure=args.measure,
                screen_family=args.screen_family, weekly_points=args.weekly_points or WEEKLY_POINTS,
            )
    except (BlockingIOError, BudgetStop) as stop:
        print(f"Calibration paused: {stop}")
    except (InstrumentError, OSError, TimeoutError, ValueError, KeyError) as error:
        parser.exit(1, f"Calibration stopped: {error}\n")


if __name__ == "__main__":
    main()
