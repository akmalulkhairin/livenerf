from datetime import date, timedelta
from types import SimpleNamespace
from xml.etree import ElementTree

from livenerf import codex_report


def test_report_preserves_gap_and_matches_csv(tmp_path, monkeypatch):
    models = ("gpt-6.2-astra", "gpt-6.2-sol")
    start = date(2026, 11, 18)
    for offset in range(11):
        folder = tmp_path / str(start + timedelta(days=offset)) / models[0]
        folder.mkdir(parents=True)
        if offset != 5:
            (folder / "complete").touch()
            (folder / "run.eval").touch()
    metric = SimpleNamespace(value=0.8)
    score = SimpleNamespace(name="compute_scorer", metrics={"mean": metric})
    samples = [
        SimpleNamespace(id=index, metadata={"cluster": cluster},
                        scores={score.name: SimpleNamespace(value=value)})
        for index, (value, cluster) in enumerate(((0.9, "a"), (0.9, "a"), (0.7, "b"), (0.7, "b")))
    ]
    log = SimpleNamespace(results=SimpleNamespace(scores=[score]), samples=samples)
    monkeypatch.setattr(codex_report, "read_eval_log", lambda *args, **kwargs: log)

    codex_report.write_report(tmp_path, models)
    csv = (tmp_path / "daily.csv").read_text().splitlines()
    assert csv[6] == "2026-11-23,,"
    assert csv[7] == "2026-11-24,0.8,"
    svg = (tmp_path / "daily.svg").read_text()
    ns = {"s": "http://www.w3.org/2000/svg"}
    chart = ElementTree.fromstring(svg)
    assert chart.attrib["viewBox"] == "0 0 960 380"
    assert len(chart.findall(".//s:circle", ns)) == 10
    bands = [path for path in chart.findall("s:path", ns) if path.attrib.get("opacity") == "0.12"]
    assert len(bands) == 2
    assert all(band.attrib["d"].count("M") == 1 for band in bands)
    assert len([line for line in chart.findall("s:line", ns) if line.attrib.get("opacity") == "0.5"]) == 10
    assert abs(codex_report.daily_scores(tmp_path, models)[0][1][models[0]].se - 0.1) < 1e-12
    assert svg.count('stroke-dasharray="6 5"') == 1
    assert "Astra baseline 80.0%" in svg
    assert "Sol 0/10" in svg
    assert 'fill="#1a1a19"' in (tmp_path / "daily-dark.svg").read_text()
    codex_report.write_report(tmp_path, models)
    assert (tmp_path / "daily.svg").read_text() == svg
