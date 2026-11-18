import time

import pytest

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
        reserve(path, limits, 2)
    weekly["usedPercent"] = 49
    with pytest.raises(BudgetStop, match="Account usage"):
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
