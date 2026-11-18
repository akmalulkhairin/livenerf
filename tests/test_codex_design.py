from collections import defaultdict

import pytest

from livenerf.codex_design import calibration_design
from livenerf.codex_panel import freeze_panel, read_panel, verified_items
from livenerf.design import daily_sensitivity


def test_design_uses_confirmed_items_and_live_nerf_sensitivity(tmp_path):
    pool = {
        "gpqa": [{"id": item, "metadata": {"item_hash": item}} for item in ("gpqa-first", "gpqa-second")],
        "aime": [{"id": "aime-excluded"}],
    }
    screen = defaultdict(lambda: {"scores": [], "errors": 0, "events": 0, "tokens": []})
    confirmation = defaultdict(lambda: {"scores": [], "errors": 0, "events": 0, "tokens": []})
    assert calibration_design(pool, screen, confirmation)["stage"] == "screen"
    with pytest.raises(ValueError, match="confirmation"):
        freeze_panel(tmp_path, calibration_design(pool, screen, confirmation))

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
    digest = freeze_panel(tmp_path, report)
    assert freeze_panel(tmp_path, report) == digest
    assert read_panel(tmp_path) == ({"study_id": tmp_path.name, **{
        key: report[key] for key in ("panel", "control", "item_hashes", "samples_per_item_per_day", "predicted_sensitivity")
    }}, digest)
    assert verified_items(report, pool) == {"gpqa-first": "gpqa", "gpqa-second": "gpqa"}
    with pytest.raises(ValueError, match="question.*changed"):
        verified_items({**report, "item_hashes": {"gpqa-first": "stale", "gpqa-second": "gpqa-second"}}, pool)
    with pytest.raises(ValueError, match="different panel"):
        freeze_panel(tmp_path, {**report, "control": []})
    (tmp_path / "panel" / "panel.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        read_panel(tmp_path)
