import json
import subprocess

import pytest

from livenerf import codex_publish
from livenerf.codex_panel import freeze_panel


def test_publication_keeps_previous_results_and_excludes_raw_logs(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    repo = tmp_path / "checkout"
    source = tmp_path / "reports"
    repo.mkdir()
    source.mkdir()
    codex_publish.git(tmp_path, "init", "--bare", str(remote))
    codex_publish.git(repo, "init", "-b", codex_publish.BRANCH)
    (repo / "README.md").write_text("# Results\n\n[Monitor](daily.csv)\n")
    (repo / "daily.csv").write_text("utc_day,existing_monitor\n")
    codex_publish.git(repo, "add", "--", "README.md", "daily.csv")
    codex_publish.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                      "commit", "-m", "test(results): seed monitor")
    codex_publish.git(repo, "push", remote.as_uri(),
                      f"{codex_publish.BRANCH}:refs/heads/{codex_publish.BRANCH}")
    for name in codex_publish.REPORTS:
        (source / name).write_text("Aggregate fixture\n")
    (source / "private.eval").write_text("Excluded fixture")
    monkeypatch.setattr(codex_publish, "REMOTE", remote.as_uri())

    study = "0123456789abcdef"
    root = tmp_path / study
    digest = freeze_panel(root, {
        "stage": "panel-candidate", "panel": ["gpqa-a", "gpqa-b"], "control": ["gpqa-a"],
        "item_hashes": {"gpqa-a": "hash-a", "gpqa-b": "hash-b"},
        "samples_per_item_per_day": 1, "predicted_sensitivity": {"se_points": 1.5, "mde_points": 5.13},
    })
    codex_publish.publish_design(root)
    codex_publish.publish_design(root)
    design = f"drift/{study}/design.json"
    assert json.loads(subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:{design}"], cwd=remote, text=True
    )) == {
        "study_id": study, "panel_sha256": digest, "astra_items": 2, "sol_items": 1,
        "samples_per_item_per_day": 1, "predicted_sensitivity": {"se_points": 1.5, "mde_points": 5.13},
    }
    readme = subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:README.md"], cwd=remote, text=True
    )
    assert design in readme and f"drift/{study}/daily.csv" not in readme
    with pytest.raises(ValueError, match="published design differs"):
        codex_publish.publish(None, study=study, design=b"{}\n")

    codex_publish.publish(source, study=study)
    codex_publish.publish(source, study=study)
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", codex_publish.BRANCH], cwd=remote, text=True
    ).splitlines()
    assert set(listing) == {"README.md", "daily.csv", design, *(f"drift/{study}/{name}" for name in codex_publish.REPORTS)}
    readme = subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:README.md"], cwd=remote, text=True
    )
    assert readme.count(f"## Drift study {study}") == 1
    assert readme.count(design) == 1
    assert f"drift/{study}/daily.csv" in readme
    assert subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:daily.csv"], cwd=remote, text=True
    ) == "utc_day,existing_monitor\n"
    revision_count = subprocess.check_output(
        ["git", "rev-list", "--count", codex_publish.BRANCH], cwd=remote, text=True
    ).strip()
    assert revision_count == "3"

    receipt = b'{"passed": true}\n'
    codex_publish.publish(None, study=study, validation=receipt)
    validation = f"drift/{study}/validation.json"
    assert subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:{validation}"], cwd=remote
    ) == receipt
    with pytest.raises(ValueError, match="published validation differs"):
        codex_publish.publish(None, study=study, validation=b'{"passed": false}\n')

    (source / "comparison.json").write_text("Aggregate comparison fixture\n")
    codex_publish.publish(source, comparison=study)
    after_comparison = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", codex_publish.BRANCH], cwd=remote, text=True
    ).splitlines()
    assert set(after_comparison) == set(listing) | {validation} | {
        f"comparison/{study}/{name}" for name in (*codex_publish.REPORTS, "comparison.json")
    }


def test_unfrozen_study_never_reaches_the_publisher(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("unfrozen study reached publisher")

    monkeypatch.setattr(codex_publish, "publish", unexpected)
    codex_publish.publish_study(tmp_path, None)
