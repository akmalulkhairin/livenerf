import csv
import math
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from tempfile import NamedTemporaryFile

from inspect_ai.log import read_eval_log

from .plot import MIN_SPAN, THEMES

BASELINE_DAYS = 10


def daily_scores(root, models):
    days = sorted(date.fromisoformat(path.name) for path in root.iterdir() if path.is_dir())
    if not days:
        return []
    rows = []
    for offset in range((days[-1] - days[0]).days + 1):
        day = days[0] + timedelta(days=offset)
        scores = {}
        for model in models:
            folder = root / day.isoformat() / model
            if (folder / "complete").is_file():
                (path,) = folder.glob("*.eval")
                log = read_eval_log(path, header_only=True)
                scores[model] = log.results.scores[0].metrics["mean"].value
        rows.append((day, scores))
    return rows


def render(rows, models, theme="light"):
    colours = THEMES[theme]
    width, height = 960, 380
    left, right, top, bottom = 64, width - 28, 92, height - 52
    start, last = rows[0][0], rows[-1][0]
    series = [
        [(day, scores[model]) for day, scores in rows if model in scores]
        for model in models
    ]
    collecting = any(len(points) < BASELINE_DAYS for points in series)
    baseline_end = max(
        points[BASELINE_DAYS - 1][0] if len(points) >= BASELINE_DAYS
        else last + timedelta(days=BASELINE_DAYS - len(points))
        for points in series
    )
    end = max(start + MIN_SPAN, max(last, baseline_end) + timedelta(days=4))
    values = [100 * score for points in series for _, score in points]
    low = max(0, 10 * math.floor((min([40, *values]) - 1) / 10))
    high = min(100, 10 * math.ceil((max([80, *values]) + 1) / 10))

    def x(day):
        return left + (right - left) * (day - start).days / (end - start).days

    def y(score):
        return top + (bottom - top) * (high - 100 * score) / (high - low)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'font-family="-apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
        '<title id="t">GPT-6.2 Astra and Sol vs. their own baselines</title>',
        '<desc id="d">Daily mean compute scores including partial credit. Missing points show incomplete runs. '
        'The shaded band shows baseline collection. Each dashed line is the mean of a model’s first ten complete runs.</desc>',
        f'<rect width="{width}" height="{height}" rx="10" fill="{colours["surface"]}"/>',
        f'<text x="{left}" y="38" fill="{colours["ink"]}" font-size="20" font-weight="600">'
        'GPT-6.2 Astra and Sol vs. their own baselines</text>',
        f'<text x="{left}" y="62" fill="{colours["ink2"]}" font-size="13">'
        'Daily mean score on the fixed 10-question compute panel. Dashed lines show baseline means.</text>',
    ]
    for percent in range(low, high + 1, 10):
        level = y(percent / 100)
        parts.append(f'<line x1="{left}" y1="{level:.1f}" x2="{right}" y2="{level:.1f}" stroke="{colours["grid"]}"/>')
        parts.append(f'<text x="{left - 10}" y="{level + 4:.1f}" text-anchor="end" '
                     f'fill="{colours["muted"]}" font-size="12">{percent}%</text>')
    parts.append(f'<rect x="{left}" y="{top}" width="{x(baseline_end) - left:.1f}" height="{bottom - top}" '
                 f'fill="{colours["band"]}" opacity="0.6"/>')
    parts.append(f'<text x="{left + 6}" y="{top + 16}" fill="{colours["ink2"]}" font-size="12">baseline collection</text>')
    parts.append(f'<text x="{left + 6}" y="{bottom - 8}" fill="{colours["muted"]}" font-size="11">day 1 · {start:%b %d}</text>')
    for offset in range(0, (end - start).days + 1, 7):
        day = start + timedelta(days=offset)
        parts.append(f'<text x="{x(day):.1f}" y="{bottom + 22}" text-anchor="middle" '
                     f'fill="{colours["muted"]}" font-size="12">{day:%b %d}</text>')

    latest_labels = []
    baseline_labels = []
    progress = []
    for name, points, colour in zip(("Astra", "Sol"), series, (colours["series"], colours["series2"]), strict=True):
        progress.append(f"{name} {min(len(points), BASELINE_DAYS)}/{BASELINE_DAYS}")
        if len(points) >= BASELINE_DAYS:
            baseline = mean(score for _, score in points[:BASELINE_DAYS])
            level = y(baseline)
            parts.append(f'<line x1="{left}" y1="{level:.1f}" x2="{right}" y2="{level:.1f}" stroke="{colour}" '
                         'stroke-width="1.5" stroke-dasharray="6 5"/>')
            baseline_labels.append((level, right - 4, "end", colour, f"{name} baseline {baseline:.1%}"))
        if not points:
            continue
        line = []
        for index, (day, score) in enumerate(points):
            connected = index > 0 and day - points[index - 1][0] == timedelta(days=1)
            line.append(f'{"L" if connected else "M"}{x(day):.1f},{y(score):.1f}')
        parts.append(f'<path d="{" ".join(line)}" fill="none" stroke="{colour}" stroke-width="2" '
                     'stroke-linejoin="round" stroke-linecap="round"/>')
        for day, score in points:
            parts.append(f'<circle cx="{x(day):.1f}" cy="{y(score):.1f}" r="3.5" fill="{colour}" '
                         f'stroke="{colours["surface"]}" stroke-width="1.5"/>')
        day, score = points[-1]
        anchor = "start" if x(day) + 120 <= right else "end"
        label_x = x(day) + (10 if anchor == "start" else -10)
        latest_labels.append((y(score), label_x, anchor, colour, f"{name} {score:.1%}"))

    for labels, min_y in ((latest_labels, top + 35), (baseline_labels, top + 14)):
        for index, (level, label_x, anchor, colour, label) in enumerate(sorted(labels)):
            line_y = min(max(level - 8, min_y), bottom - 4 - 17 * (len(labels) - index - 1))
            parts.append(f'<text x="{label_x:.1f}" y="{line_y:.1f}" text-anchor="{anchor}" '
                         f'fill="{colour}" font-size="13" font-weight="600">{label}</text>')
            min_y = line_y + 17
    if collecting:
        midpoint = (x(baseline_end) + right) / 2
        parts.append(f'<text x="{midpoint:.1f}" y="{(top + bottom) / 2:.1f}" text-anchor="middle" '
                     f'fill="{colours["muted"]}" font-size="14">Collecting the baseline · {" · ".join(progress)}</text>')
    parts.append(f'<text x="{right}" y="{height - 12}" text-anchor="end" '
                 f'fill="{colours["muted"]}" font-size="11">Data through {last:%Y-%m-%d} UTC</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_report(root, models):
    if not root.exists() or not (rows := daily_scores(root, models)):
        return
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=root, delete=False) as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(("utc_day", *models))
        writer.writerows((day, *(scores.get(model) for model in models)) for day, scores in rows)
    Path(file.name).replace(root / "daily.csv")
    for theme, name in (("light", "daily.svg"), ("dark", "daily-dark.svg")):
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as file:
            file.write(render(rows, models, theme))
        Path(file.name).replace(root / name)
