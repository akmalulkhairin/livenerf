import sys
from datetime import datetime, timezone
from subprocess import CalledProcessError

import pytest

from livenerf import codex_series
from livenerf.codex_budget import BudgetStop, daily_capacity


def test_two_point_reservations_cannot_sustain_daily_series():
    assert daily_capacity(2) == {
        "weekly_cap_points": 10,
        "minimum_weekly_reservation_points": 15,
        "maximum_days_per_week": 4,
        "supports_daily_series": False,
    }
    assert daily_capacity(1)["supports_daily_series"]


def test_series_requires_passing_validation(tmp_path, monkeypatch):
    panel = {"panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a", "gpqa-b"], "samples_per_item_per_day": 1}
    monkeypatch.setattr(codex_series, "read_panel", lambda root: (panel, "digest"))
    monkeypatch.setattr(codex_series, "verified_items", lambda *args: {})
    monkeypatch.setattr(codex_series, "validation_rows", lambda *args: [])
    with pytest.raises(ValueError, match="has not passed"):
        codex_series.ready_panel(tmp_path, {})


def test_main_does_not_start_a_baseline_that_cannot_fit_the_week(tmp_path, monkeypatch, capsys):
    (tmp_path / "study" / "test" / "panel").mkdir(parents=True)
    panel = {"panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a", "gpqa-b"]}
    monkeypatch.setattr(sys, "argv", ["codex_series", "--run"])
    monkeypatch.setattr(codex_series, "STUDY_HOME", tmp_path / "instrument")
    monkeypatch.setattr(codex_series, "LOADERS", {})
    monkeypatch.setattr(codex_series, "study_id", lambda: "test")
    monkeypatch.setattr(codex_series, "restore_aime_2026", lambda: None)
    monkeypatch.setattr(codex_series, "ready_panel", lambda *args: (panel, "digest", {}))
    monkeypatch.setattr(codex_series, "run_day", lambda *args: pytest.fail("would start a baseline"))
    codex_series.main()
    assert "weekly reservation policy cannot sustain" in capsys.readouterr().out


def test_unpublished_design_prevents_baseline(tmp_path, monkeypatch, capsys):
    root = tmp_path / "study" / "test"
    (root / "panel").mkdir(parents=True)
    panel = {"panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a", "gpqa-b"]}

    def failed_publication(path):
        assert path == root
        raise CalledProcessError(1, "git push")

    monkeypatch.setattr(sys, "argv", ["codex_series", "--run"])
    monkeypatch.setattr(codex_series, "STUDY_HOME", tmp_path / "instrument")
    monkeypatch.setattr(codex_series, "LOADERS", {})
    monkeypatch.setattr(codex_series, "study_id", lambda: "test")
    monkeypatch.setattr(codex_series, "restore_aime_2026", lambda: None)
    monkeypatch.setattr(codex_series, "ready_panel", lambda *args: (panel, "digest", {}))
    monkeypatch.setattr(codex_series, "PREFLIGHT_RESERVATION", 1)
    monkeypatch.setattr(codex_series, "publish_design", failed_publication)
    monkeypatch.setattr(codex_series, "run_day", lambda *args: pytest.fail("would start a baseline"))
    with pytest.raises(SystemExit) as stopped:
        codex_series.main()
    assert stopped.value.code == 1
    assert "Series stopped: Command 'git push'" in capsys.readouterr().err


def test_series_resumes_one_attempt_per_arm_with_one_daily_reservation(tmp_path, monkeypatch):
    panel = {"panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a"]}
    families = {"gpqa-a": "gpqa", "gpqa-b": "gpqa"}
    day = datetime.now(timezone.utc).date().isoformat()
    allowances = []
    runs = []
    interrupted = True

    async def read_limits():
        return {}

    def reserve(path, meter, points):
        allowances.append(points)
        if interrupted and allowances == [2, 0, 0]:
            raise BudgetStop("Test interruption")

    def evaluate(task, **kwargs):
        runs.append((kwargs["sample_id"][0], kwargs["model"], kwargs["metadata"]["arm"]))
        assert kwargs["metadata"]["panel_sha256"] == "digest"

    monkeypatch.setattr(codex_series, "STUDY_HOME", tmp_path / "instrument")
    monkeypatch.setattr(codex_series, "check_version", lambda: None)
    monkeypatch.setattr(codex_series, "read_limits", read_limits)
    monkeypatch.setattr(codex_series, "reserve", reserve)
    monkeypatch.setattr(codex_series.tasks, "gpqa", lambda **kwargs: None)
    monkeypatch.setattr(codex_series, "eval", evaluate)

    with pytest.raises(BudgetStop):
        codex_series.run_day(tmp_path, day, panel, "digest", families)
    interrupted = False
    codex_series.run_day(tmp_path, day, panel, "digest", families)
    codex_series.run_day(tmp_path, day, panel, "digest", families)
    assert allowances.count(2) == 1
    assert runs == [
        ("gpqa-a", "codex-study/gpt-6.2-astra", "measured"),
        ("gpqa-b", "codex-study/gpt-6.2-astra", "measured"),
        ("gpqa-a", "codex-study/gpt-6.2-sol", "control"),
    ]
