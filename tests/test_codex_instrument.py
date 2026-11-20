import time

import pytest

from livenerf import codex_budget
from livenerf.codex_budget import BudgetStop, reserve
from livenerf.providers.codex.instrument import InstrumentError, validate_event


def test_reservations_survive_restarts_and_include_meter_movement(tmp_path):
    path = tmp_path / "quota.json"
    weekly = {"usedPercent": 17, "resetsAt": int(time.time()) + 3600, "windowDurationMins": 10080}
    limits = {"primary": weekly}
    assert reserve(path, limits, 2) == (17, 2)
    weekly["usedPercent"] = 20
    weekly["resetsAt"] += 30
    assert reserve(path, limits, 2) == (20, 7)
    weekly["usedPercent"] = 21
    with pytest.raises(BudgetStop, match="weekly allowance"):
        reserve(path, limits, 2, weekly_points=10)
    weekly["usedPercent"] = 49
    with pytest.raises(BudgetStop, match="Account usage"):
        reserve(path, limits, 2)


def test_new_week_releases_only_previous_window_reservations(tmp_path, monkeypatch):
    path = tmp_path / "quota.json"
    clock = 1_000_000
    monkeypatch.setattr(codex_budget.time, "time", lambda: clock)
    reset = clock + 60
    limits = {"primary": {"usedPercent": 20, "resetsAt": reset, "windowDurationMins": 10080}}
    for booked in range(2, 20, 2):
        assert reserve(path, limits, 2) == (20, booked)
    limits["primary"]["resetsAt"] += 30
    with pytest.raises(BudgetStop, match="weekly allowance"):
        reserve(path, limits, 2)
    clock = reset + 30
    limits["primary"] = {"usedPercent": 0, "resetsAt": reset + 604800, "windowDurationMins": 10080}
    assert reserve(path, limits, 2) == (0, 2)


def test_manual_allowance_uses_the_same_ledger_and_account_stop(tmp_path):
    path = tmp_path / "quota.json"
    weekly = {"usedPercent": 20, "resetsAt": int(time.time()) + 3600, "windowDurationMins": 10080}
    limits = {"primary": weekly}
    for _ in range(9):
        reserve(path, limits, 2)
    with pytest.raises(BudgetStop, match="weekly allowance"):
        reserve(path, limits, 2)
    assert reserve(path, limits, 2, weekly_points=30) == (20, 20)
    with pytest.raises(BudgetStop, match="weekly allowance"):
        reserve(path, limits, 0)
    weekly["usedPercent"] = 48
    with pytest.raises(BudgetStop, match="Account usage"):
        reserve(path, limits, 2, weekly_points=55)


@pytest.mark.parametrize("allowance", ["90", "off"])
def test_scheduled_allowance_expires_at_the_named_reset(tmp_path, monkeypatch, allowance):
    path = tmp_path / "quota.json"
    clock = 1_000_000
    monkeypatch.setattr(codex_budget.time, "time", lambda: clock)
    reset = clock + 60
    monkeypatch.setenv("LIVENERF_STUDY_ALLOWANCE", f"{reset}:{allowance}")
    limits = {"primary": {"usedPercent": 31, "resetsAt": reset, "windowDurationMins": 10080}}
    for _ in range(12):
        reserve(path, limits, 2)
    limits["primary"]["resetsAt"] += 30
    assert reserve(path, limits, 2) == (31, 26)
    limits["primary"]["usedPercent"] = 48
    with pytest.raises(BudgetStop, match="Account usage"):
        reserve(path, limits, 2)

    clock = reset + 1
    limits["primary"].update(usedPercent=0, resetsAt=reset + 604800)
    for _ in range(9):
        reserve(path, limits, 2)
    with pytest.raises(BudgetStop, match="weekly allowance"):
        reserve(path, limits, 2)


@pytest.mark.parametrize(("event", "marker"), (
    ({"method": "model/rerouted"}, "[fallback]"),
    ({"method": "error", "params": {"willRetry": True}}, "[retried]"),
    ({"method": "item/completed", "params": {
        "item": {"type": "agentMessage", "moderation": {"moderated": True}}
    }}, "[refusal]"),
))
def test_instrument_rejects_observable_invalid_turns(event, marker):
    with pytest.raises(InstrumentError) as error:
        validate_event(event)
    assert marker in str(error.value)
