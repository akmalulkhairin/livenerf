import argparse
import fcntl
import json
import os

from .benchmarks import calibrate
from .benchmarks.data import LOADERS
from .codex_calibrate import restore_aime_2026, study_id
from .codex_panel import freeze_panel
from .design import calibrated_candidates, daily_sensitivity
from .providers.codex.instrument import STUDY_HOME


def calibration_design(pool, screen, confirmation):
    progress = {}
    for family, items in pool.items():
        ids = [item["id"] for item in items]
        progress[family] = {
            "questions": len(ids),
            "screen_scored": sum(len(screen[item]["scores"]) for item in ids),
            "screen_pending": sum(calibrate.screen_wanted(screen[item]) for item in ids),
            "confirmation_pending": sum(calibrate.confirm_wanted(screen[item], confirmation[item]) for item in ids),
        }
    if any(family["screen_pending"] for family in progress.values()):
        return {"stage": "screen", "progress": progress}
    if any(family["confirmation_pending"] for family in progress.values()):
        return {"stage": "confirmation", "progress": progress}

    candidates = calibrated_candidates(pool, screen, confirmation)
    panel = sorted((item for item in candidates if item["eligible"]), key=lambda item: item["id"])
    unconfirmed = [item["id"] for item in panel if not item["confirmed"]]
    control = [item["id"] for item in panel if item["family"] == "gpqa"]
    if unconfirmed or len(panel) < 2 or len(control) < 2:
        return {"stage": "design-blocked", "progress": progress, "unconfirmed": unconfirmed,
                "eligible": len(panel), "control_items": len(control)}
    panel_ids = [item["id"] for item in panel]
    selected = set(panel_ids)
    return {
        "stage": "panel-candidate", "progress": progress,
        "panel": panel_ids, "control": control,
        "item_hashes": {item["id"]: item["metadata"]["item_hash"]
                        for items in pool.values() for item in items if item["id"] in selected},
        "samples_per_item_per_day": 1, "predicted_sensitivity": daily_sensitivity(panel),
    }


def main():
    parser = argparse.ArgumentParser(description="Report calibration progress or a candidate panel from saved Codex results.")
    parser.add_argument("--freeze", action="store_true", help="Freeze a confirmed candidate panel for validation")
    args = parser.parse_args()
    restore_aime_2026()
    pool = {family: loader() for family, loader in LOADERS.items()}
    identifier = study_id()
    root = STUDY_HOME.parent / "study" / identifier
    if args.freeze:
        os.umask(0o077)
        try:
            with (STUDY_HOME.parent / ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                design = calibration_design(pool, calibrate.history(root / "screen"), calibrate.history(root / "confirmation"))
                design["panel_sha256"] = freeze_panel(root, design)
        except (OSError, ValueError) as error:
            parser.exit(1, f"Could not freeze the panel: {error}\n")
    else:
        design = calibration_design(pool, calibrate.history(root / "screen"), calibrate.history(root / "confirmation"))
    print(json.dumps({"study_id": identifier, **design}, indent=2))


if __name__ == "__main__":
    main()
