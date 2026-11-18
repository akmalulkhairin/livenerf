import subprocess
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from .codex_daily import series_id

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


def publish(source):
    if not all((source / name).is_file() for name in REPORTS):
        print("No daily report is ready to publish.", flush=True)
        return
    with TemporaryDirectory(prefix="livenerf-publication-") as directory:
        git(directory, "clone", "--depth", "1", "--single-branch", "--branch", BRANCH, REMOTE, ".")
        for name in REPORTS:
            copyfile(source / name, Path(directory) / name)
        readme = Path(directory) / "README.md"
        original = readme.read_text()
        updated = original.replace(
            FIRST_REPORT, f"{DAILY_PICTURE}\n\n[Daily scores CSV](daily.csv)"
        ).replace("![Daily benchmark scores](daily.svg)", DAILY_PICTURE).replace(
            "![Pilot mean scores for Astra and Sol](pilot.svg)", "[Pilot chart](pilot.svg)"
        )
        if updated != original:
            readme.write_text(updated)
        git(directory, "add", "--", "README.md", *REPORTS)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=directory, timeout=15)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            diff.check_returncode()
        git(directory, "diff", "--staged", "--check")
        git(directory, "diff", "--check")
        git(directory, "-c", "user.name=LiveNerf for Codex",
            "-c", "user.email=akmalulkhairin@users.noreply.github.com",
            "commit", "-m", f"chore(results): publish Codex series {source.name}")
        git(directory, "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "push", "origin", f"{BRANCH}:refs/heads/{BRANCH}")


if __name__ == "__main__":
    publish(Path.home() / ".local/state/livenerf-codex" / series_id())
