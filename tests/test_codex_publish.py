import subprocess

from livenerf import codex_publish


def test_drift_publication_keeps_monitor_and_excludes_raw_logs(tmp_path, monkeypatch):
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
    codex_publish.publish(source, study=study)
    codex_publish.publish(source, study=study)
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", codex_publish.BRANCH], cwd=remote, text=True
    ).splitlines()
    assert set(listing) == {"README.md", "daily.csv", *(f"drift/{study}/{name}" for name in codex_publish.REPORTS)}
    assert subprocess.check_output(
        ["git", "show", f"{codex_publish.BRANCH}:daily.csv"], cwd=remote, text=True
    ) == "utc_day,existing_monitor\n"
    revision_count = subprocess.check_output(
        ["git", "rev-list", "--count", codex_publish.BRANCH], cwd=remote, text=True
    ).strip()
    assert revision_count == "2"


def test_unfrozen_study_never_reaches_the_publisher(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("unfrozen study reached publisher")

    monkeypatch.setattr(codex_publish, "publish", unexpected)
    codex_publish.publish_study(tmp_path, None)
