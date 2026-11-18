import argparse
import asyncio
import fcntl
import json
import math
import os
from collections import Counter

import pandas as pd
from inspect_ai import eval
from inspect_ai.log import list_eval_logs, read_eval_log

from .benchmarks import tasks
from .benchmarks.data import LOADERS
from .codex_budget import BudgetStop, reserve
from .codex_calibrate import PREFLIGHT_RESERVATION, read_limits, restore_aime_2026, study_id
from .codex_panel import read_panel, verified_items
from .providers.codex.instrument import MODEL, STUDY_HOME, InstrumentError, check_version
from .validate import MAX_ERRORS, REPS, _paired, _paired_tokens

ARMS = {
    "high": (MODEL, "high"),
    "medium": (MODEL, "medium"),
    "low": (MODEL, "low"),
    "control": ("gpt-6.2-sol", "high"),
}


def required_pairs(panel):
    return [(item, arm) for arm in ARMS
            for item in (panel["control"] if arm == "control" else panel["panel"])]


def validation_rows(root, panel, digest):
    directory = root / "validation"
    pairs = set(required_pairs(panel))
    rows = []
    if not directory.exists():
        return rows
    for info in list_eval_logs(str(directory)):
        log = read_eval_log(info)
        metadata = log.eval.metadata or {}
        arm = metadata.get("arm")
        if (metadata.get("study_id") != root.name or metadata.get("panel_sha256") != digest
                or arm not in ARMS or log.eval.model != f"codex-study/{ARMS[arm][0]}"):
            raise ValueError("A validation log does not match the frozen study and arm")
        for sample in log.samples or ():
            if ((sample.id, arm) not in pairs
                    or sample.metadata.get("item_hash") != panel["item_hashes"][sample.id]):
                raise ValueError("A validation sample does not match the frozen question")
            usage = next(iter(sample.model_usage.values()), None)
            score = next(iter(sample.scores.values()), None) if sample.scores else None
            rows.append({
                "id": sample.id, "effort": arm, "cluster": sample.metadata.get("cluster") or sample.id,
                "created": log.eval.created, "error": bool(sample.error or score is None or usage is None),
                "score": float(score.value) if score else None,
                "output_tokens": usage.output_tokens if usage else None,
            })
    return rows


def pending_pairs(panel, rows):
    scored = Counter((row["id"], row["effort"]) for row in rows if not row["error"])
    errors = Counter((row["id"], row["effort"]) for row in rows if row["error"])
    return sorted(
        (pair for pair in required_pairs(panel) if scored[pair] < REPS and errors[pair] < MAX_ERRORS),
        key=lambda pair: (scored[pair], errors[pair], pair[0],
                          (list(ARMS).index(pair[1]) - scored[pair]) % len(ARMS)),
    )


def validation_result(panel, rows):
    pending = pending_pairs(panel, rows)
    scored = [row for row in rows if not row["error"]]
    report = {"pending_pairs": len(pending), "scored": len(scored), "errors": len(rows) - len(scored), "passed": False}
    if pending or not scored:
        return report

    good = pd.DataFrame(scored)
    arms = {arm: good[good["effort"] == arm] for arm in ARMS}
    high = arms["high"].sort_values("created").assign(rep=lambda df: df.groupby("id").cumcount())
    aa = _paired(high[high["rep"] % 2 == 0], high[high["rep"] % 2 == 1])
    lo, hi = _paired_tokens(high, arms["low"])["ci99_pct"]
    swap_accuracy = _paired(high, arms["control"])
    swap_usage = _paired_tokens(high, arms["control"])
    control_covered = swap_accuracy["items"] >= 2
    report.update(
        aa_consistent=bool(abs(aa["z"]) < 1.96),
        lower_effort_token_ci99=[value if math.isfinite(value) else None for value in (lo, hi)],
        control_items=swap_accuracy["items"],
        control_distinguishable=bool(abs(swap_accuracy["z"]) > 2.576 or abs(swap_usage["z"]) > 2.576),
        passed=bool(abs(aa["z"]) < 1.96 and (lo > 0 or hi < 0) and control_covered),
    )
    return report


def run_batch(root, panel, digest, families, limit):
    pending = pending_pairs(panel, validation_rows(root, panel, digest))[:limit]
    if not pending:
        return
    check_version()
    budget = STUDY_HOME.parent / "study-budget.json"
    reserve(budget, asyncio.run(read_limits()), PREFLIGHT_RESERVATION)
    task_by_family = {}
    for item, arm in pending:
        reserve(budget, asyncio.run(read_limits()), 0)
        family = families[item]
        if family not in task_by_family:
            task_by_family[family] = getattr(tasks, family)(panel="all")
        model, effort = ARMS[arm]
        eval(
            task_by_family[family], model=f"codex-study/{model}", effort=effort,
            log_dir=str(root / "validation"), sample_id=[item], max_connections=1, max_retries=0,
            metadata={"study_id": root.name, "panel_sha256": digest, "arm": arm},
            tags=["livenerf-codex", "validation", arm], display="none",
        )


def main():
    parser = argparse.ArgumentParser(description="Check instrument validation or run a budgeted batch.")
    parser.add_argument("--batch", type=int, choices=range(1, 17), metavar="SIZE")
    args = parser.parse_args()
    os.umask(0o077)
    root = STUDY_HOME.parent / "study" / study_id()
    try:
        panel, digest = read_panel(root)
        restore_aime_2026()
        families = verified_items(panel, {family: load() for family, load in LOADERS.items()})
        if args.batch:
            with (STUDY_HOME.parent / ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                run_batch(root, panel, digest, families, args.batch)
        report = validation_result(panel, validation_rows(root, panel, digest))
        print(json.dumps({"study_id": root.name, "panel_sha256": digest, **report}, indent=2))
    except (BudgetStop, BlockingIOError) as stop:
        print(f"Validation paused: {stop}")
    except (InstrumentError, OSError, TimeoutError, KeyError, ValueError) as error:
        parser.exit(1, f"Validation stopped: {error}\n")


if __name__ == "__main__":
    main()
