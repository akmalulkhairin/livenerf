import argparse
import csv
import fcntl
import hashlib
import json
import os
from datetime import date, datetime, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, stdev
from tempfile import TemporaryDirectory

from inspect_ai.log import read_eval_log

from .benchmarks.tasks import PANEL_FILE, family_items
from .codex_budget import WEEKLY_POINTS, BudgetStop
from .codex_calibrate import restore_aime_2026, study_id
from .codex_publish import publish
from .codex_report import DailyEstimate, write_charts
from .codex_series import run_day
from .codex_validate import ARMS
from .common import REPO_ROOT
from .providers.codex.instrument import CLI_VERSION, STUDY_HOME, InstrumentError

UPSTREAM_COMMIT = "52ca4d947f4a84be849099c1f28de10b33ec1b77"
PANEL_LOCK = "487c65e15230286e5f4818ef70749a94e0b4052a381413ce527bb087a5f846da"
ITEM_DIGEST = "2c2110c9b375c1858a1569b14c559afb51898998da18e874db1038a6601b9090"
GRADING_DIGEST = "2cd8e73b3b9211d606ce67ef7f11f0ee42280cf10999686d7ee8117fd0524730"
GRADING_FILES = (
    "livenerf/benchmarks/tasks.py", "livenerf/benchmarks/data.py",
    "livenerf/scorers/__init__.py", "livenerf/scorers/checks.py", "prompts/system_v1.txt",
)
FAMILY_SIZES = {"gpqa": 12, "mmlupro": 59, "comps": 4, "aime": 3}
COMPARISON_ARMS = {"measured": ARMS["high"], "control": ARMS["control"]}


def upstream_panel():
    data = PANEL_FILE.read_bytes()
    windows_bytes = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    lock = PANEL_FILE.with_name("panel.lock").read_text().strip()
    if lock != PANEL_LOCK or hashlib.sha256(windows_bytes).hexdigest() != PANEL_LOCK:
        raise ValueError("The upstream panel does not match its published lock")

    grading = hashlib.sha256()
    for name in GRADING_FILES:
        grading.update(name.encode() + b"\0" + hashlib.sha256((REPO_ROOT / name).read_bytes()).digest())
    if grading.hexdigest() != GRADING_DIGEST:
        raise ValueError("The upstream tasks, graders or prompt changed")

    items = {family: {row["id"]: row["metadata"]["item_hash"] for row in family_items(family, "daily")}
             for family in FAMILY_SIZES}
    if {name: len(selected) for name, selected in items.items()} != FAMILY_SIZES:
        raise ValueError("The frozen upstream family sizes changed")
    canonical = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != ITEM_DIGEST:
        raise ValueError("The frozen upstream question contents changed")
    families = {item: family for family, selected in items.items() for item in selected}
    ids = list(families)
    return {"panel": ids, "control": ids,
            "item_hashes": {item: items[family][item] for item, family in families.items()}}, families


def comparison_id():
    identity = f"{UPSTREAM_COMMIT}\0{PANEL_LOCK}\0{ITEM_DIGEST}\0{GRADING_DIGEST}\0{study_id()}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def sample_score(directory, item, item_hash, model, effort):
    logs = list((directory / item).glob("*.eval"))
    if not logs:
        return None
    log_path, = logs
    log = read_eval_log(log_path)
    if log.eval.model != f"codex-study/{model}" or log.eval.model_generate_config.effort != effort:
        raise ValueError("A saved comparison sample used a different model or effort")
    if log.eval.metadata.get("panel_sha256") != ITEM_DIGEST or log.eval.metadata.get("cli_version") != CLI_VERSION:
        raise ValueError("A saved comparison sample used a different panel or CLI")
    if log.status != "success" or not log.samples or len(log.samples) != 1:
        return None
    sample = log.samples[0]
    if sample.id != item or sample.metadata.get("item_hash") != item_hash:
        raise ValueError("A saved comparison sample contains a different question")
    if sample.error or not sample.scores:
        return None
    score, = sample.scores.values()
    if score.value not in (0, 1):
        raise ValueError("An upstream comparison score must be zero or one")
    return score.value


def claude_references():
    references = []
    sources = (("daily.csv", "claudecode/claude-opus-5-5"),
               ("fable52_bridge.csv", "claudecode/claude-fable-5-2"))
    for name, model in sources:
        with (REPO_ROOT / "results" / name).open() as file:
            row = max((row for row in csv.DictReader(file)
                       if row["model"] == model and row["family"] == "all" and row["scored"] == "78"),
                      key=lambda row: row["date_utc"])
        references.append({
            "model": model, "utc_day": row["date_utc"], "score": float(row["score"]),
            "scored": int(row["scored"]), "cli_version": row["cli_version"], "effort": "high",
            "harness": row.get("harness_sha", row.get("harness_hash")),
            "source": f"https://github.com/ninjahawk/livenerf/blob/main/results/{name}",
        })
    return references


def write_comparison(root, day, panel, output):
    directory = root / "series" / day
    scores = {}
    counts = {}
    for arm, (model, effort) in COMPARISON_ARMS.items():
        values = [sample_score(directory / arm, item, panel["item_hashes"][item], model, effort)
                  for item in panel["panel"]]
        if any(value is None for value in values):
            return False
        scores[model] = DailyEstimate(mean(values), stdev(values) / sqrt(len(values)))
        counts[model] = {"correct": int(sum(values)), "scored": len(values), "effort": effort}

    with (output / "daily.csv").open("w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(("utc_day", *scores))
        writer.writerow((day, *(score.mean for score in scores.values())))
    write_charts(output, [(date.fromisoformat(day), scores)], tuple(scores), comparison=True)
    (output / "comparison.json").write_text(json.dumps({
        "upstream_panel_revision": UPSTREAM_COMMIT, "upstream_panel_lock": PANEL_LOCK,
        "item_digest": ITEM_DIGEST, "grading_digest": GRADING_DIGEST, "families": FAMILY_SIZES,
        "utc_day": day, "codex_cli": CLI_VERSION, "models": counts, "claude_references": claude_references(),
    }, indent=2, sort_keys=True) + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Check or run the shared 78-question comparison.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--day", type=date.fromisoformat, help="Publish a saved UTC date")
    parser.add_argument("--weekly-points", type=int, default=WEEKLY_POINTS)
    args = parser.parse_args()
    if args.weekly_points < WEEKLY_POINTS:
        parser.error(f"The comparison requires a study allowance of at least {WEEKLY_POINTS} points.")
    if args.day and not args.publish:
        parser.error("--day requires --publish.")
    os.umask(0o077)
    try:
        restore_aime_2026()
        panel, families = upstream_panel()
        root = STUDY_HOME.parent / "comparison" / comparison_id()
        day = (args.day or datetime.now(timezone.utc).date()).isoformat()
        print(f"Shared-panel comparison {root.name} for {day}. {len(families)} questions per model.", flush=True)
        if args.run or args.publish:
            with (STUDY_HOME.parent / ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if args.run:
                    run_day(root, day, panel, ITEM_DIGEST, families, comparison_cap=args.weekly_points)
                else:
                    with TemporaryDirectory(prefix="livenerf-comparison-") as directory:
                        output = Path(directory)
                        if not write_comparison(root, day, panel, output):
                            raise ValueError("Astra and Sol both need all 78 scores before publication")
                        publish(output, comparison=root.name)
    except (BudgetStop, BlockingIOError) as stop:
        print(f"Comparison paused: {stop}")
    except (InstrumentError, OSError, TimeoutError, ValueError, KeyError) as error:
        parser.exit(1, f"Comparison stopped: {error}\n")


if __name__ == "__main__":
    main()
