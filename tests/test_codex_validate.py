from livenerf.codex_validate import required_pairs, validation_result


def test_validation_reuses_paired_checks_and_limits_sol_to_shared_questions():
    panel = {"panel": ["gpqa-a", "gpqa-b", "aime-a"], "control": ["gpqa-a", "gpqa-b"]}
    pairs = required_pairs(panel)
    assert ("aime-a", "control") not in pairs
    assert validation_result(panel, [])["pending_pairs"] == 11

    high_scores = {"gpqa-a": [0, 1, 0, 0], "gpqa-b": [1, 0, 0, 0], "aime-a": [0, 0, 1, 1]}
    low_usage = {"gpqa-a": 20, "gpqa-b": 23, "aime-a": 19}
    rows = [
        {"id": item, "effort": arm, "cluster": item, "created": index, "error": False, "score": score,
         "output_tokens": low_usage[item] if arm == "low" else 100}
        for item, arm in pairs
        for index, score in enumerate(high_scores[item])
    ]
    assert not validation_result(panel, rows[:-1])["passed"]
    report = validation_result(panel, rows)
    assert report["passed"]
    assert report["aa_consistent"]
    assert report["control_items"] == 2
    assert report["lower_effort_token_ci99"][1] < 0
