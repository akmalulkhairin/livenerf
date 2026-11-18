from collections import defaultdict

import pytest

from livenerf.codex_design import calibration_design
from livenerf.design import daily_sensitivity


def test_design_uses_confirmed_items_and_live_nerf_sensitivity():
    pool = {
        "gpqa": [{"id": item} for item in ("gpqa-first", "gpqa-second")],
        "aime": [{"id": "aime-excluded"}],
    }
    screen = defaultdict(lambda: {"scores": [], "errors": 0, "events": 0, "tokens": []})
    confirmation = defaultdict(lambda: {"scores": [], "errors": 0, "events": 0, "tokens": []})
    assert calibration_design(pool, screen, confirmation)["stage"] == "screen"

    for item in ("gpqa-first", "gpqa-second", "aime-excluded"):
        screen[item].update(scores=[0, 0, 0, 1], tokens=[100])
    assert calibration_design(pool, screen, confirmation)["stage"] == "confirmation"

    confirmation["gpqa-first"].update(scores=[1] * 8, tokens=[100])
    confirmation["gpqa-second"].update(scores=[0, 1] * 4, tokens=[100])
    confirmation["aime-excluded"].update(errors=2, events=1)
    report = calibration_design(pool, screen, confirmation)
    assert report["stage"] == "panel-candidate"
    assert report["panel"] == report["control"] == ["gpqa-first", "gpqa-second"]
    assert report["predicted_sensitivity"] == pytest.approx(daily_sensitivity([{"p": 0.9}, {"p": 0.5}]))
