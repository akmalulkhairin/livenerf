import subprocess
import sys

from .codex_budget import daily_capacity
from .codex_calibrate import MEASUREMENT_SAMPLES, PREFLIGHT_RESERVATION, study_id
from .codex_panel import read_panel
from .codex_validate import validation_result, validation_rows
from .providers.codex.instrument import STUDY_HOME


def commands_for_study(root):
    if not (root / "panel").exists():
        return [("codex_calibrate", "--batch", str(MEASUREMENT_SAMPLES))]

    panel, digest = read_panel(root)
    validation = validation_result(panel, validation_rows(root, panel, digest))
    if validation["pending_pairs"]:
        return [("codex_validate", "--batch", "16")]
    if not validation["passed"]:
        print("Validation finished without passing. Review the instrument and control before the baseline.", flush=True)
        return [("codex_validate",)]
    if not daily_capacity(PREFLIGHT_RESERVATION)["supports_daily_series"]:
        print("The weekly reservation policy cannot sustain the daily series.", flush=True)
        return [("codex_series",)]
    return [("codex_series", "--run"), ("codex_publish", "--study")]


def main():
    try:
        commands = commands_for_study(STUDY_HOME.parent / "study" / study_id())
        for module, *args in commands:
            subprocess.run([sys.executable, "-m", f"livenerf.{module}", *args], check=True)
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Study workflow stopped: {error}") from error


if __name__ == "__main__":
    main()
