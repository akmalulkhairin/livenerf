import argparse
import asyncio
import fcntl
import hashlib
import io
import json
import os
import urllib.request
from datetime import datetime, timezone

import pandas as pd
from inspect_ai import eval

from .benchmarks import calibrate, tasks
from .benchmarks.data import AIME_SHA256, LOADERS, _aime_norm, cache_dir
from .codex_budget import BudgetStop, reserve, usage_percent
from .common import REPO_ROOT
from .providers.codex.instrument import CLI_VERSION, MODEL, STUDY_HOME, InstrumentError, app_server, check_version

AIME_2026_REVISION = "d2de22f3c656b4f56cf8981212186377d1e23bc3"
STUDY_EFFORT = "high"
PREFLIGHT_RESERVATION = 2


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


async def read_limits():
    async with asyncio.timeout(20), app_server() as (server, _):
        return (await server.request("account/rateLimits/read", {}))["rateLimits"]


def collect_batch(root, pool, size):
    screen = calibrate.history(root / "screen")
    confirmation = calibrate.history(root / "confirmation")
    stage = "screen"
    pending = next_batch(pool, screen, confirmation, stage, size)
    if not pending:
        stage = "confirmation"
        pending = next_batch(pool, screen, confirmation, stage, size)
    if not pending:
        print("Screening and confirmation are complete.")
        return

    budget = STUDY_HOME.parent / "study-budget.json"
    used, points = reserve(budget, asyncio.run(read_limits()), PREFLIGHT_RESERVATION)
    print(f"{stage}: up to {len(pending)} samples. Weekly meter {used}%, study points reserved {points}.", flush=True)
    completed = 0
    output_tokens = 0
    scored = 0
    task_by_family = {}
    try:
        for family, item_id in pending:
            reserve(budget, asyncio.run(read_limits()), 0)
            if family not in task_by_family:
                task_by_family[family] = getattr(tasks, family)(panel="all")
            (log,) = eval(
                task_by_family[family], model=f"codex-study/{MODEL}", effort=STUDY_EFFORT,
                sample_id=[item_id], log_dir=str(root / stage), max_connections=1, max_retries=0,
                display="none", tags=["livenerf-codex", "calibration", stage],
                metadata={"study_id": root.name},
            )
            completed += 1
            scored += sum(not sample.error and bool(sample.scores) for sample in (log.samples or ()))
            output_tokens += sum(usage.output_tokens for usage in log.stats.model_usage.values())
            print(f"{stage}: {completed}/{len(pending)} attempted, {scored} scored.", flush=True)
    finally:
        try:
            weekly_after = usage_percent(asyncio.run(read_limits())["primary"])
        except (InstrumentError, BudgetStop, TimeoutError, OSError, KeyError, ValueError):
            weekly_after = None
        with (root / "batches.jsonl").open("a") as file:
            file.write(json.dumps({
                "utc": datetime.now(timezone.utc).isoformat(), "stage": stage, "weekly_before": used,
                "weekly_after": weekly_after, "attempts": completed, "scored": scored, "output_tokens": output_tokens,
            }) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Check the pinned Codex calibration pool or collect a batch.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--one", action="store_const", dest="size", const=1, help="Collect one sample")
    mode.add_argument("--batch", type=int, dest="size", metavar="SIZE", help="Collect up to 16 samples")
    args = parser.parse_args()
    if args.size is not None and not 1 <= args.size <= calibrate.CHUNK:
        parser.error(f"Batch size must be between 1 and {calibrate.CHUNK}.")
    os.umask(0o077)
    try:
        restore_aime_2026()
        pool = {family: loader() for family, loader in LOADERS.items()}
        for family, items in pool.items():
            print(f"{family}: {len(items)} questions verified", flush=True)
        root = STUDY_HOME.parent / "study" / study_id()
        print(f"Study {root.name}", flush=True)
        if args.size is None:
            return
        check_version()
        with (STUDY_HOME.parent / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            root.mkdir(parents=True, exist_ok=True)
            collect_batch(root, pool, args.size)
    except (BlockingIOError, BudgetStop) as stop:
        print(f"Calibration paused: {stop}")
    except (InstrumentError, OSError, TimeoutError, ValueError, KeyError) as error:
        parser.exit(1, f"Calibration stopped: {error}\n")


if __name__ == "__main__":
    main()
