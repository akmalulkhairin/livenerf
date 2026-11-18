from livenerf import codex_workflow


def test_scheduled_workflow_respects_panel_validation_and_budget(tmp_path, monkeypatch):
    assert codex_workflow.commands_for_study(tmp_path) == [("codex_calibrate", "--batch", "64")]
    (tmp_path / "panel").mkdir()
    validation = {"pending_pairs": 1, "passed": False}
    monkeypatch.setattr(codex_workflow, "read_panel", lambda root: ({}, "digest"))
    monkeypatch.setattr(codex_workflow, "validation_rows", lambda *args: [])
    monkeypatch.setattr(codex_workflow, "validation_result", lambda *args: validation)
    publication = ("codex_publish", "--design")
    assert codex_workflow.commands_for_study(tmp_path) == [publication, ("codex_validate", "--batch", "16")]

    validation["pending_pairs"] = 0
    assert codex_workflow.commands_for_study(tmp_path) == [publication, ("codex_validate",)]
    validation["passed"] = True
    with monkeypatch.context() as smaller_allowance:
        smaller_allowance.setattr(codex_workflow, "PREFLIGHT_RESERVATION", 3)
        assert codex_workflow.commands_for_study(tmp_path) == [publication, ("codex_series",)]

    assert codex_workflow.commands_for_study(tmp_path) == [
        ("codex_series", "--run"), ("codex_publish", "--study")
    ]
