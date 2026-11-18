from datetime import datetime, timezone

import pytest

from livenerf import codex_series
from livenerf.codex_budget import BudgetStop


def test_series_requires_passing_validation(tmp_path, monkeypatch):
    panel = {"panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a", "gpqa-b"], "samples_per_item_per_day": 1}
    monkeypatch.setattr(codex_series, "read_panel", lambda root: (panel, "digest"))
    monkeypatch.setattr(codex_series, "verified_items", lambda *args: {})
    monkeypatch.setattr(codex_series, "validation_rows", lambda *args: [])
    with pytest.raises(ValueError, match="has not passed"):
        codex_series.ready_panel(tmp_path, {})


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
