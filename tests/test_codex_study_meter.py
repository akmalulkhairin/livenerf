import json
from subprocess import CompletedProcess

import pytest

from livenerf import codex_study_meter


@pytest.mark.parametrize("phase", ["validation", "daily"])
def test_meter_keeps_readings_only_for_new_daily_attempts(tmp_path, monkeypatch, phase):
    day = "2026-11-20"
    before = {"used_percent": 30}
    after = {"used_percent": 31}
    readings = iter([before, after])
    monkeypatch.setattr(codex_study_meter, "meter_reading", lambda: next(readings))

    def run(args):
        assert args[-2:] == ["livenerf.codex_upstream_study", "--run"]
        directory = tmp_path / "validation" if phase == "validation" else tmp_path / "series" / day / "measured" / "a"
        directory.mkdir(parents=True)
        (directory / "a.eval").touch()
        return CompletedProcess(args, 0)

    monkeypatch.setattr(codex_study_meter.subprocess, "run", run)
    assert codex_study_meter.run_with_meter(tmp_path) == 0
    receipt = tmp_path / "quota-readings.jsonl"
    if phase == "validation":
        assert not receipt.exists()
    else:
        assert json.loads(receipt.read_text()) == {
            "utc_days": {day: 1}, "before": before, "after": after, "exit_status": 0,
        }
