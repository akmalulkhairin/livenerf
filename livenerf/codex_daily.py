import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import eval

from .codex_report import write_report
from .common import REPO_ROOT
from .providers.codex import codex_environment
from .tasks.suite import compute

MODELS = ("gpt-6.2-astra", "gpt-6.2-sol")
SAMPLES = tuple(f"compute-{index:03}" for index in range(10))
CLI_VERSION = "codex-cli 0.169.1"
EFFORT = "low"
USAGE_CEILING = 50


def series_id():
    files = ("uv.lock", "livenerf/codex_daily.py", "livenerf/common.py", "livenerf/_registry.py",
             "livenerf/providers/codex/__init__.py", "livenerf/tasks/suite.py", "prompts/system_v1.txt")
    paths = [REPO_ROOT / name for name in files]
    for directory in ("livenerf/generators", "livenerf/scorers"):
        paths.extend((REPO_ROOT / directory).glob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]


def permitted_usage(limits):
    primary = limits["primary"]
    windows = [primary]
    if limits.get("secondary") is not None:
        windows.append(limits["secondary"])
    percentages = [window["usedPercent"] for window in windows]
    if any(type(value) is not int or not 0 <= value <= 100 for value in percentages):
        raise ValueError("Invalid Codex usage reading")
    print(f"Codex usage windows: {percentages}%. Ceiling: {USAGE_CEILING}%.", flush=True)
    return max(percentages) < USAGE_CEILING


async def read_meter():
    process = await asyncio.create_subprocess_exec(
        "codex", "-c", 'forced_login_method="chatgpt"', "app-server",
        env=codex_environment(), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(20):
            process.stdin.write(
                b'{"id":1,"method":"initialize","params":{"clientInfo":{"name":"livenerf","version":"1"}}}\n'
                b'{"method":"initialized"}\n'
                b'{"id":2,"method":"account/rateLimits/read"}\n'
            )
            await process.stdin.drain()
            while line := await process.stdout.readline():
                event = json.loads(line)
                if event.get("id") == 2:
                    return event["result"]["rateLimits"]
            raise ValueError("Codex closed its usage connection")
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def attempt_day(root, day, dry_run):
    task = compute(panel="public")
    if not set(SAMPLES).issubset({sample.id for sample in task.dataset}):
        raise ValueError("The fixed compute sample IDs are missing")
    version = subprocess.check_output(
        ["codex", "--version"], env=codex_environment(), text=True, timeout=20
    ).strip()
    if version != CLI_VERSION:
        raise ValueError(f"Expected {CLI_VERSION}, found {version}")

    failed = False
    if not dry_run:
        (root / day).mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        destination = root / day / model
        if destination.exists():
            if not (destination / "complete").is_file():
                print(f"{model}: incomplete attempt preserved at {destination}", flush=True)
                failed = True
            continue
        if not permitted_usage(asyncio.run(read_meter())):
            print("Usage ceiling reached. Remaining models skipped.", flush=True)
            break
        if dry_run:
            print(f"{model}: ready for {len(SAMPLES)} samples", flush=True)
            continue
        try:
            destination.mkdir(parents=True, mode=0o700)
        except FileExistsError:
            print(f"{model}: another process claimed this attempt", flush=True)
            continue
        (log,) = eval(
            task, model=f"codex/{model}", model_args={"expect_cli_version": version},
            sample_id=list(SAMPLES), effort=EFFORT, max_connections=1, max_retries=0,
            log_dir=str(destination), display="plain",
        )
        if log.status == "success" and len(log.samples or ()) == len(SAMPLES) and all(
            sample.error is None and sample.scores for sample in log.samples
        ):
            (destination / "complete").touch()
        else:
            failed = True
            print(f"{model}: incomplete attempt preserved at {destination}", flush=True)
    return int(failed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "logs" / "codex" / "daily")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--report", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    day = datetime.now(timezone.utc).date().isoformat()
    root = args.logs / series_id()
    print(f"Codex series {root.name}, UTC day {day}", flush=True)
    try:
        if args.dry_run:
            return attempt_day(root, day, True)
        args.logs.mkdir(parents=True, exist_ok=True)
        with (args.logs / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Another Codex daily run is active.", flush=True)
                return 0
            result = 0 if args.report else attempt_day(root, day, False)
            write_report(root, MODELS)
            return result
    except (OSError, KeyError, TypeError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Codex run stopped: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
