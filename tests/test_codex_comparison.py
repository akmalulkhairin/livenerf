import csv
import json

from livenerf import codex_comparison


def test_report_requires_complete_pair(tmp_path, monkeypatch):
    items = [f"question-{n}" for n in range(78)]
    panel = {"panel": items, "item_hashes": {item: item for item in items}}
    missing = {"question-77"}

    def score(directory, item, item_hash, model, effort):
        assert effort == "high"
        if directory.name == "control" and item == "question-77":
            return None if item in missing else 0
        return 1

    monkeypatch.setattr(codex_comparison, "sample_score", score)
    output = tmp_path / "public"
    output.mkdir()
    assert not codex_comparison.write_comparison(tmp_path, "2026-11-19", panel, output)
    assert not list(output.iterdir())

    missing.clear()
    assert codex_comparison.write_comparison(tmp_path, "2026-11-19", panel, output)
    with (output / "daily.csv").open() as file:
        row, = csv.DictReader(file)
    assert float(row["gpt-6.2-astra"]) == 1
    assert float(row["gpt-6.2-sol"]) == 77 / 78
    charts = [(output / name).read_text() for name in ("daily.svg", "daily-dark.svg")]
    assert all("95% intervals" in chart and "baseline collection" not in chart for chart in charts)
    receipt = json.loads((output / "comparison.json").read_text())
    assert receipt["models"]["gpt-6.2-sol"]["correct"] == 77
    assert len(receipt["claude_references"]) == 2
