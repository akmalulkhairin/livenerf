import json
import time
from types import SimpleNamespace

import pytest

from livenerf import codex_calibrate
from livenerf.codex_budget import BudgetStop


def test_batch_checks_budget_before_each_call(tmp_path, monkeypatch):
    meter = iter((18, 18, 26, 26))
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
    with pytest.raises(BudgetStop, match="weekly allowance"):
        codex_calibrate.collect_batch(tmp_path, pool, 2)

    assert results == ["gpqa-first"]
    recorded = json.loads((tmp_path / "batches.jsonl").read_text())
    assert (recorded["attempts"], recorded["weekly_before"], recorded["weekly_after"]) == (1, 18, 26)
