import json
import time
from types import SimpleNamespace

import pytest

from livenerf import codex_calibrate
from livenerf.codex_budget import BudgetStop


@pytest.mark.parametrize(("measure", "final_usage", "reason"), (
    (False, 26, "weekly allowance"),
    (True, 21, "meter moved by at least"),
))
def test_batch_checks_budget_before_each_call(tmp_path, monkeypatch, measure, final_usage, reason):
    meter = iter((18, 18, final_usage, final_usage))
    results = []
    pool = {"gpqa": [{"id": item_id} for item_id in ("gpqa-first", "gpqa-second")]}
    reset = int(time.time()) + 3600

    async def read_limits():
        return {"primary": {"usedPercent": next(meter), "resetsAt": reset, "windowDurationMins": 10080}}

    def evaluate(task, **kwargs):
        results.extend(kwargs["sample_id"])
        return (SimpleNamespace(
            samples=[SimpleNamespace(error=None, scores={"choice": 1})],
            stats=SimpleNamespace(model_usage={}),
        ),)

    monkeypatch.setattr(codex_calibrate, "STUDY_HOME", tmp_path / "instrument")
    monkeypatch.setattr(codex_calibrate, "read_limits", read_limits)
    monkeypatch.setattr(codex_calibrate.tasks, "gpqa", lambda **kwargs: None)
    monkeypatch.setattr(codex_calibrate, "eval", evaluate)
    with pytest.raises(BudgetStop, match=reason):
        codex_calibrate.collect_batch(tmp_path, pool, 2, measure=measure)

    assert results == ["gpqa-first"]
    recorded = json.loads((tmp_path / "batches.jsonl").read_text())
    assert (recorded["attempts"], recorded["weekly_before"], recorded["weekly_after"]) == (1, 18, final_usage)
    assert (tmp_path / "study-budget.json").exists() is not measure


def test_measurement_resumes_with_original_limit_despite_reset_timestamp_change(tmp_path):
    reset = int(time.time()) + 3600
    original = {"mode": "measurement", "weekly_before": 19, "weekly_reset": reset, "attempts": 15}
    (tmp_path / "batches.jsonl").write_text(json.dumps(original) + "\n")
    limits = {"primary": {"usedPercent": 19, "resetsAt": reset + 30, "windowDurationMins": 10080}}
    window = codex_calibrate.measurement_window(tmp_path, limits, 16)
    assert window == {"start": 19, "reset": reset, "attempts": 15}
    codex_calibrate.record_measurement_attempt(tmp_path, window)
    with pytest.raises(BudgetStop, match="sample limit"):
        codex_calibrate.measurement_window(tmp_path, limits, 16)


def test_larger_batches_stay_within_measured_screening_family():
    science = [("gpqa", str(index)) for index in range(48)]
    maths = [("aime", str(index)) for index in range(48)]
    assert codex_calibrate.scheduled_items(science + maths, "screen") == science
    assert codex_calibrate.scheduled_items(maths + science, "screen") == maths[:16]
    assert codex_calibrate.scheduled_items(science + maths, "confirmation") == science[:16]
