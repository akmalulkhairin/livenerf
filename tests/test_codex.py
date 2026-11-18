import pytest

from livenerf.providers.codex import read_turn


def test_read_turn_rejects_tool_use():
    usage = {"input_tokens": 10, "output_tokens": 2}
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "42"}},
        {"type": "turn.completed", "usage": usage},
    ]
    assert read_turn(events, 0) == ("42", usage)
    events.insert(0, {"type": "item.completed", "item": {"type": "command_execution"}})
    with pytest.raises(ValueError, match="text-only turn"):
        read_turn(events, 0)
