import argparse
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

import pandas as pd

from .codex_analysis import report, write_formal_report
from .codex_calibrate import study_id
from .codex_daily import series_id
from .codex_panel import read_panel
from .codex_validate import validation_result, validation_rows
from .providers.codex.instrument import STUDY_HOME

REMOTE = "https://github.com/akmalulkhairin/livenerf.git"
BRANCH = "codex-results"
REPORTS = ("daily.csv", "daily.svg", "daily-dark.svg")
FIRST_REPORT = "<!-- Daily report appears after the first completed run. -->"
DAILY_PICTURE = """<picture>
  <source media="(prefers-color-scheme: dark)" srcset="daily-dark.svg">
  <img alt="Daily compute scores for Astra and Sol against their own baselines" src="daily.svg">
</picture>"""


def git(directory, *args):
    return subprocess.run(["git", *args], cwd=directory, check=True, timeout=60)


def study_readme(original, study, *, design, daily):
    section = f"## Drift study {study}\n"
    path = f"drift/{study}"
    links = ""
    if design and f"{path}/design.json" not in original:
        links += f"\n[Frozen panel summary and predicted sensitivity]({path}/design.json)\n"
    if daily and f"{path}/daily.csv" not in original:
        links += f"""
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="{path}/daily-dark.svg">
  <img alt="Daily scores and baseline progress for the calibrated drift study" src="{path}/daily.svg">
</picture>

[Daily scores CSV]({path}/daily.csv)
"""
    if not links:
        return original
    before, heading, after = original.partition(section)
    if heading:
        return before + heading + links + after
    return original.rstrip() + "\n\n" + section + links


def publish(source, *, study=None, design=None, comparison=None):
    if study is not None and not re.fullmatch(r"[a-f0-9]{16}", study):
        raise ValueError("A drift publication requires a verified study ID")
    if source is None and (study is None or design is None):
        raise ValueError("A design publication requires a verified study ID and design")
    if comparison is not None and (study is not None or design is not None or not re.fullmatch(r"[a-f0-9]{16}", comparison)):
        raise ValueError("A comparison publication requires a verified comparison ID")
    required = (*REPORTS, "comparison.json") if comparison else REPORTS
    if source is not None and not all((source / name).is_file() for name in required):
        print("No daily report is ready to publish.", flush=True)
        return
    with TemporaryDirectory(prefix="livenerf-publication-") as directory:
        git(directory, "clone", "--depth", "1", "--single-branch", "--branch", BRANCH, REMOTE, ".")
        checkout = Path(directory)
        reports = checkout
        if study:
            reports = checkout / "drift" / study
        elif comparison:
            reports = checkout / "comparison" / comparison
        reports.mkdir(parents=True, exist_ok=True)
        names = list(required) if source is not None else []
        for name in names:
            copyfile(source / name, reports / name)
        if design is not None:
            path = reports / "design.json"
            if path.exists() and path.read_bytes() != design:
                raise ValueError("The published design differs from the frozen panel")
            path.write_bytes(design)
            names.append(path.name)
        readme = checkout / "README.md"
        original = readme.read_text()
        if study:
            updated = study_readme(original, study, design=design is not None, daily=source is not None)
        elif comparison:
            path = f"comparison/{comparison}"
            updated = original
            if f"{path}/comparison.json" not in original:
                updated = original.rstrip() + f"""

## Upstream frozen panel comparison

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="{path}/daily-dark.svg">
  <img alt="Astra and Sol on the same 78 questions" src="{path}/daily.svg">
</picture>

[Scores CSV]({path}/daily.csv) · [Panel, run settings and dated Claude references]({path}/comparison.json)
"""
        else:
            updated = original.replace(
                FIRST_REPORT, f"{DAILY_PICTURE}\n\n[Daily scores CSV](daily.csv)"
            ).replace("![Daily benchmark scores](daily.svg)", DAILY_PICTURE).replace(
                "![Pilot mean scores for Astra and Sol](pilot.svg)", "[Pilot chart](pilot.svg)"
            )
        if updated != original:
            readme.write_text(updated)
        git(directory, "add", "--", "README.md", *(str((reports / name).relative_to(checkout)) for name in names))
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=directory, timeout=15)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            diff.check_returncode()
        git(directory, "diff", "--staged", "--check")
        git(directory, "diff", "--check")
        git(directory, "-c", "user.name=LiveNerf for Codex",
            "-c", "user.email=akmalulkhairin@users.noreply.github.com",
            "commit", "-m", f"chore(results): publish Codex {'design' if design else 'series'} "
            f"{study or comparison or source.name}")
        git(directory, "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "push", "origin", f"{BRANCH}:refs/heads/{BRANCH}")


def publish_design(root):
    panel, digest = read_panel(root)
    sensitivity = panel["predicted_sensitivity"]
    summary = {
        "study_id": root.name,
        "panel_sha256": digest,
        "astra_items": len(panel["panel"]),
        "sol_items": len(panel["control"]),
        "samples_per_item_per_day": panel["samples_per_item_per_day"],
        "predicted_sensitivity": {key: sensitivity[key] for key in ("se_points", "mde_points")},
    }
    design = (json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    publish(None, study=root.name, design=design)


def publish_study(root, now):
    if not (root / "panel").exists():
        print("No frozen study is ready to publish.")
        return
    panel, digest = read_panel(root)
    if not validation_result(panel, validation_rows(root, panel, digest))["passed"]:
        raise ValueError("The frozen panel has not passed instrument validation")
    prepared = write_formal_report(root, report(root, now))
    if prepared:
        publish(prepared, study=root.name)


def main():
    parser = argparse.ArgumentParser(description="Publish aggregate Codex benchmark results.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--study", action="store_true", help="Publish the validated drift series")
    mode.add_argument("--design", action="store_true", help="Publish the frozen panel's aggregate design")
    args = parser.parse_args()
    state = STUDY_HOME.parent
    if args.study or args.design:
        if not state.is_dir():
            print("No frozen study is ready to publish.")
            return
        os.umask(0o077)
        with (state / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            root = state / "study" / study_id()
            if args.design:
                publish_design(root)
            else:
                publish_study(root, pd.Timestamp.now(tz="UTC"))
    else:
        publish(state / series_id())


if __name__ == "__main__":
    main()
