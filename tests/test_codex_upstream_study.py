import json
from subprocess import CalledProcessError

import pytest

from livenerf import codex_upstream_study as study
from livenerf.codex_validate import ARMS, MAX_ERRORS, REPS, validation_result


PANEL = {"panel": ["a", "b"], "control": ["a", "b"], "upstream_revision": "upstream"}


@pytest.fixture
def completed_validation():
    return [
        {"id": item, "effort": arm, "cluster": item, "created": rep, "error": False, "score": score,
         "output_tokens": {"high": 100, "medium": 75, "low": 25, "control": 40}[arm] + 5 * index}
        for arm in ARMS
        for index, (item, scores) in enumerate({"a": [1, 1, 0, 1], "b": [1, 0, 1, 1]}.items())
        for rep, score in enumerate(scores)
    ]


def test_study_publishes_validation_before_admitting_baseline(tmp_path, monkeypatch, completed_validation):
    rows = []
    calls = []

    def run_batch(root, panel, digest, families, limit, *, task_panel):
        assert task_panel == "daily" and limit == 4
        rows.extend(completed_validation)

    def publish_design(root, *, validation=None):
        calls.append("validation" if validation else "design")
        if validation:
            receipt = json.loads(validation)
            assert receipt["validation"]["passed"]
            assert receipt["replicates_per_question_and_arm"] == REPS
            assert set(receipt["validation"]["paired_checks"]) == {"low", "medium", "control"}

    def run_day(*args, task_panel):
        assert task_panel == "daily"
        calls.append("daily run")

    monkeypatch.setattr(study, "validation_rows", lambda *args: rows)
    monkeypatch.setattr(study, "run_batch", run_batch)
    monkeypatch.setattr(study, "publish_design", publish_design)
    monkeypatch.setattr(study, "run_day", run_day)
    monkeypatch.setattr(study, "report", lambda *args: {})
    monkeypatch.setattr(study, "write_formal_report", lambda *args: None)
    study.advance_study(tmp_path, PANEL, "digest", {})
    assert calls == ["design", "validation"]

    def failed_publication(*args, **kwargs):
        raise CalledProcessError(1, "git push")

    with monkeypatch.context() as failed:
        failed.setattr(study, "publish_design", failed_publication)
        with pytest.raises(CalledProcessError):
            study.advance_study(tmp_path, PANEL, "digest", {})
        assert "daily run" not in calls

    study.advance_study(tmp_path, PANEL, "digest", {})
    assert calls[-2:] == ["validation", "daily run"]


def test_exhausted_validation_pair_blocks_the_baseline(completed_validation):
    rows = [row for row in completed_validation if (row["id"], row["effort"]) != ("b", "low")]
    rows.extend({"id": "b", "effort": "low", "error": True} for _ in range(MAX_ERRORS))
    result = validation_result(PANEL, rows)
    assert result["pending_pairs"] == 0
    assert result["short_pairs"] == 1
    assert not result["passed"]
