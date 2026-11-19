import json
import sys
import time
from types import SimpleNamespace

import pytest

from livenerf import codex_calibrate
from livenerf.codex_budget import BudgetStop


@pytest.mark.parametrize(("measure", "final_usage", "reason"), (
    (False, 36, "weekly allowance"),
    (True, 21, "meter moved by at least"),
))
def test_batch_checks_budget_before_each_call(tmp_path, monkeypatch, measure, final_usage, reason):
    meter = iter((18, 18, final_usage, final_usage))
    results = []
    family = "gpqa" if measure else "mmlupro"
    pool = {family: [{"id": f"{family}-{item}"} for item in ("first", "second")]}
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
    monkeypatch.setattr(codex_calibrate.tasks, family, lambda **kwargs: None)
    monkeypatch.setattr(codex_calibrate, "eval", evaluate)
    with pytest.raises(BudgetStop, match=reason):
        codex_calibrate.collect_batch(tmp_path, pool, 2, measure=measure)

    assert results == [f"{family}-first"]
    recorded = json.loads((tmp_path / "batches.jsonl").read_text())
    assert (recorded["attempts"], recorded["weekly_before"], recorded["weekly_after"]) == (1, 18, final_usage)
    assert recorded["weekly_batch_before"] == 18
    assert recorded["attempts_by_family"] == {family: 1}
    assert recorded["scored_by_family"] == {family: 1}
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


@pytest.mark.parametrize("family", ("gpqa", "mmlupro"))
def test_larger_batches_stay_within_measured_screening_family(family):
    measured = [(family, str(index)) for index in range(128)]
    maths = [("aime", str(index)) for index in range(48)]
    assert codex_calibrate.scheduled_items(measured + maths, "screen") == measured
    assert codex_calibrate.scheduled_items(maths + measured, "screen") == maths[:16]
    assert codex_calibrate.scheduled_items(measured + maths, "confirmation") == measured[:16]


@pytest.mark.parametrize("family", ("gpqa", "mmlupro", "comps", "aime"))
def test_manual_large_batches_require_a_measured_family(tmp_path, monkeypatch, family):
    monkeypatch.setattr(sys, "argv", ["codex_calibrate", "--batch", "128", "--screen-family", family])
    monkeypatch.setattr(codex_calibrate, "STUDY_HOME", tmp_path / "instrument")
    monkeypatch.setattr(codex_calibrate, "restore_aime_2026", lambda: None)
    monkeypatch.setattr(codex_calibrate, "study_id", lambda: "test")
    monkeypatch.setattr(codex_calibrate, "check_version", lambda: None)
    monkeypatch.setattr(codex_calibrate, "LOADERS", {family: lambda: []})
    calls = []
    monkeypatch.setattr(codex_calibrate, "collect_batch",
                        lambda root, pool, size, **kwargs: calls.append((size, kwargs["screen_family"])))

    if family in {"comps", "aime"}:
        with pytest.raises(SystemExit) as error:
            codex_calibrate.main()
        assert error.value.code == 2 and not calls
    else:
        codex_calibrate.main()
        assert calls == [(128, family)]
