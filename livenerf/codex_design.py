import argparse
import json

from .benchmarks import calibrate
from .benchmarks.data import LOADERS
from .codex_calibrate import restore_aime_2026, study_id
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
    return {
        "stage": "panel-candidate", "progress": progress,
        "panel": [item["id"] for item in panel], "control": control,
        "samples_per_item_per_day": 1, "predicted_sensitivity": daily_sensitivity(panel),
    }


def main():
    parser = argparse.ArgumentParser(description="Report calibration progress or a candidate panel from saved Codex results.")
    parser.parse_args()
    restore_aime_2026()
    pool = {family: loader() for family, loader in LOADERS.items()}
    identifier = study_id()
    root = STUDY_HOME.parent / "study" / identifier
    design = calibration_design(pool, calibrate.history(root / "screen"), calibrate.history(root / "confirmation"))
    print(json.dumps({"study_id": identifier, **design}, indent=2))


if __name__ == "__main__":
    main()
