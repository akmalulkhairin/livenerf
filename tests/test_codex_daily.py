from types import SimpleNamespace

import pytest

from livenerf import codex_daily


def test_usage_gate_checks_both_windows():
    assert codex_daily.permitted_usage({"primary": {"usedPercent": 17}})
    assert not codex_daily.permitted_usage(
        {"primary": {"usedPercent": 17}, "secondary": {"usedPercent": 50}}
    )
    with pytest.raises(ValueError, match="Invalid"):
        codex_daily.permitted_usage({"primary": {"usedPercent": -1}})


def test_daily_keeps_incomplete_attempt_and_does_not_spend_twice(tmp_path, monkeypatch):
    async def read_meter():
        return {"primary": {"usedPercent": 17}}

    runs = []

    def evaluate(task, **kwargs):
        assert tuple(kwargs["sample_id"]) == codex_daily.SAMPLES
        assert kwargs["max_retries"] == 0
        runs.append(kwargs["model"])
        samples = [SimpleNamespace(error=None, scores={"compute": 1})] * len(codex_daily.SAMPLES)
        if len(runs) == 1:
            return (SimpleNamespace(status="success", samples=samples[:-1]),)
        return (SimpleNamespace(status="success", samples=samples),)

    monkeypatch.setattr(codex_daily.subprocess, "check_output", lambda *a, **kw: codex_daily.CLI_VERSION)
    monkeypatch.setattr(codex_daily, "read_meter", read_meter)
    monkeypatch.setattr(codex_daily, "eval", evaluate)
    assert codex_daily.attempt_day(tmp_path, "2026-11-18", True) == 0
    assert not list(tmp_path.iterdir())
    assert codex_daily.attempt_day(tmp_path, "2026-11-18", False) == 1
    assert codex_daily.attempt_day(tmp_path, "2026-11-18", False) == 1
    assert runs == [f"codex/{model}" for model in codex_daily.MODELS]
    assert list(tmp_path.glob("*/*/complete")) == [tmp_path / "2026-11-18/gpt-6.2-sol/complete"]
