import argparse
import fcntl
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


def study_readme(original, study):
    section = f"## Drift study {study}"
    if section in original:
        return original
    path = f"drift/{study}"
    return original.rstrip() + f"""

{section}

The frozen Astra panel and shared Sol control are reported here. The earlier
public compute monitor appears above.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="{path}/daily-dark.svg">
  <img alt="Daily scores and baseline progress for the calibrated drift study" src="{path}/daily.svg">
</picture>

[Daily scores CSV]({path}/daily.csv)
"""


def publish(source, *, study=None):
    if study is not None and not re.fullmatch(r"[a-f0-9]{16}", study):
        raise ValueError("A drift publication requires a verified study ID")
    if not all((source / name).is_file() for name in REPORTS):
        print("No daily report is ready to publish.", flush=True)
        return
    with TemporaryDirectory(prefix="livenerf-publication-") as directory:
        git(directory, "clone", "--depth", "1", "--single-branch", "--branch", BRANCH, REMOTE, ".")
        checkout = Path(directory)
        reports = checkout / "drift" / study if study else checkout
        reports.mkdir(parents=True, exist_ok=True)
        for name in REPORTS:
            copyfile(source / name, reports / name)
        readme = checkout / "README.md"
        original = readme.read_text()
        updated = study_readme(original, study) if study else original.replace(
            FIRST_REPORT, f"{DAILY_PICTURE}\n\n[Daily scores CSV](daily.csv)"
        ).replace("![Daily benchmark scores](daily.svg)", DAILY_PICTURE).replace(
            "![Pilot mean scores for Astra and Sol](pilot.svg)", "[Pilot chart](pilot.svg)"
        )
        if updated != original:
            readme.write_text(updated)
        git(directory, "add", "--", "README.md", *(str((reports / name).relative_to(checkout)) for name in REPORTS))
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=directory, timeout=15)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            diff.check_returncode()
        git(directory, "diff", "--staged", "--check")
        git(directory, "diff", "--check")
        git(directory, "-c", "user.name=LiveNerf for Codex",
            "-c", "user.email=akmalulkhairin@users.noreply.github.com",
            "commit", "-m", f"chore(results): publish Codex series {study or source.name}")
        git(directory, "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "push", "origin", f"{BRANCH}:refs/heads/{BRANCH}")


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
    parser.add_argument("--study", action="store_true", help="Publish the validated drift series")
    args = parser.parse_args()
    state = STUDY_HOME.parent
    if args.study:
        if not state.is_dir():
            print("No frozen study is ready to publish.")
            return
        os.umask(0o077)
        with (state / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            publish_study(state / "study" / study_id(), pd.Timestamp.now(tz="UTC"))
    else:
        publish(state / series_id())


if __name__ == "__main__":
    main()
