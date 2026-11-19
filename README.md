<div align="center">

# LiveNerf for Codex

*Tracking sustained changes in GPT performance as served through the Codex CLI.*

<p>
  <a href="https://github.com/akmalulkhairin/livenerf/actions/workflows/ci.yml"><img src="https://github.com/akmalulkhairin/livenerf/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/models-GPT--6.2%20Astra%20%2B%20Sol-2a78d6?style=flat-square" alt="Models GPT-6.2 Astra and Sol">
  <a href="#study-status"><img src="https://img.shields.io/badge/study-shared_panel-e8a13c?style=flat-square" alt="Shared panel comparison"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-brightgreen?style=flat-square" alt="MIT licence"></a>
</p>

[The plan](docs/CODEX_PROTOCOL.md) · [Results](#results) · [How it works](#how-it-works) · [Upstream protocol](PREREGISTRATION.md) · [Cite](#cite)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/akmalulkhairin/livenerf/codex-results/daily-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/akmalulkhairin/livenerf/codex-results/daily.svg">
  <img alt="Daily compute scores and baseline progress for GPT-6.2 Astra and Sol" src="https://raw.githubusercontent.com/akmalulkhairin/livenerf/codex-results/daily.svg" width="100%">
</picture>

</div>

---

This fork adapts [LiveNerf](https://github.com/ninjahawk/livenerf) to study
GPT-6.2 through Codex. It reuses upstream's benchmark sources, Inspect tasks
and graders. The chart and aggregate scores reflect Codex runs.

## Study status

Astra and Sol each run the [same 78 questions as upstream](docs/adr/0002-use-the-upstream-frozen-panel.md).
The ten-question monitor continues until the first shared-panel chart is public.
The first matched run is a comparison. The formal drift baseline starts after
instrument and sensitivity validation. The earlier Astra calibration is paused.

## Results

- [Monitoring chart and CSV](https://github.com/akmalulkhairin/livenerf/tree/codex-results)
- [Pilot CSV](https://github.com/akmalulkhairin/livenerf/blob/codex-results/pilot.csv)

The monitor's grader awards partial credit. A blank score means the run was
missing or incomplete. The chart shows approximate 95% confidence intervals
for daily scores, with variability clustered by question template. The
[study decision record](docs/adr/0001-use-livenerf-protocol-for-codex-drift-study.md)
describes the separate decision rule for sustained change.

## How it works

- **Daily compute monitor.** The monitor runs ten questions per model and
  checks the live 50% account stop before each model. Its timer is scheduled
  ahead of the study timer.
- **Benchmark on the workstation.** The [study timer](scripts/systemd/livenerf-codex-calibrate.timer)
  advances calibration, validation or the daily series when the phase is ready.
  It uses a dedicated Codex profile and checks account usage before every sample.
  A failed service can restart twice, with five minutes between attempts.
  During the daily series, a restart resumes at the remaining questions for
  that UTC day.
- **Reports from saved logs.** The monitoring runner turns complete runs into a
  CSV and light and dark SVG charts. A local publisher pushes only the
  aggregates to the results branch. Raw captures and account sign-in stay local.
- **Tests on GitHub.** [CI](.github/workflows/ci.yml) checks the runner, provider,
  scoring and reporting, and verifies that the public panel can be regenerated.
  It uses no Codex login or quota.

### Reproduce locally

Run `uv run --locked python -m livenerf.codex_comparison` to verify the shared
panel, graders and prompts. Pass `--run` to collect the current UTC day's
comparison at high effort. Pass `--publish` to publish a complete pair of
results. The published summary includes the original dates and settings of
the Claude reference scores.

The benchmark requires Python 3.11+, `uv` and the pinned Codex CLI.
On Linux, the systemd units are under [scripts/systemd](scripts/systemd).

```sh
uv sync --locked
uv run --locked pytest -q
CODEX_HOME="$HOME/.local/state/livenerf-codex/instrument" codex login
uv run --locked python -m livenerf.providers.codex.instrument
uv run --locked python -m livenerf.codex_calibrate
```

The last two commands check the instrument and dataset pins without submitting
benchmark questions. To run a single sample, pass `--one` to the calibration
command. The runner checks the account meter before allowing the call.

Use `python -m livenerf.codex_design` to check calibration progress and,
once confirmation is complete, inspect the candidate panel and predicted
sensitivity. After reviewing the candidate, `codex_design --freeze` records its
question IDs, content hashes, control subset and predicted sensitivity under a
SHA-256 lock. The freeze command requires a confirmed candidate.
After the freeze, the timer publishes the panel digest, arm sizes and predicted
sensitivity before starting validation. The design appears on the
[results branch](https://github.com/akmalulkhairin/livenerf/tree/codex-results).
To publish it manually, use `python -m livenerf.codex_publish --design`.

`python -m livenerf.codex_validate` verifies the frozen panel and reports
validation progress. Its `--batch` option collects budgeted validation
samples. Astra runs at three effort levels on the panel. Sol runs on the
shared GPQA questions. The A/A check splits Astra's high-effort samples to
check that the instrument does not report a change between like runs.

After validation, `python -m livenerf.codex_series` checks readiness for
the frozen UTC-day series. The `--run` option attempts one sample per
question and arm, resumes pending questions on the same day and checks
the quota before each attempt. Drift runs use their own logs, separate
from calibration and the public compute monitor.
The series checks that the frozen design is public before collecting samples.

`python -m livenerf.codex_analysis` reports closed 10-day windows and
applies upstream's paired decision rule. It keeps gaps in the UTC
calendar and counts missing scheduled samples against window coverage.
When Sol's comparison is incomplete, the report leaves attribution open.
Pass `--write` to generate the local drift chart and daily scores CSV. The
chart uses the same error bars and baseline shading as the monitor. Drift
reports stay separate from the ten-question monitoring results.
Use `python -m livenerf.codex_publish --study` to publish the validated
study's aggregate CSV and charts. It keeps each study in its own results
directory and adds a link from the results README. It requires saved
series samples before it can publish anything. The scheduled workflow
runs the same publisher after an admitted series attempt.

A manually authorised `codex_calibrate --measure` pass collects up
to 64 samples or stops after a three-point rise in the weekly meter.
It keeps the account-wide stop and leaves the scheduled budget in place.
The scheduled runner can screen up to 128 questions in a single GPQA or
MMLU-Pro batch, matching the measured workloads. Other families and
confirmation use up to 16 questions per batch.

For an authorised larger screening batch, run `python -m livenerf.codex_calibrate
--batch 128 --screen-family mmlupro --weekly-points 30` with the agreed weekly
cap. It books the batch against the same local budget ledger and applies the
account-wide stop before each sample. The scheduled cap is 20 points.
The study ledger adds the rise in weekly account usage, the two-point
reservation for each admitted batch in that window and one point of
headroom. Reservations stay in the ledger until the weekly reset.

### Integrate upstream changes

Merge upstream into a separate branch, run CI locally and check the
calibration preflight before merging to `main`.

```sh
git remote add upstream https://github.com/ninjahawk/livenerf.git
git fetch upstream
git switch -c integrate-upstream
git merge upstream/main
uv sync --locked
uv run --locked pytest -q
uv run --locked python -m livenerf.codex_calibrate
```

Add the upstream remote only once. Deploy a tested revision to a separate
directory under `~/.local/share/livenerf-codex/`. Switch its `current` symlink
after checking the CLI pin and dataset sources. A change to the prompts,
sample-shaping code or dependency lock starts a new study series.

## Acknowledgements

- Original benchmark, reporting design and charts from [LiveNerf](https://github.com/ninjahawk/livenerf).
- Evaluation framework from [Inspect](https://inspect.aisi.org.uk/), developed
  by the UK AI Security Institute and Meridian Labs.
- Upstream's statistical method follows [Adding Error Bars to Evals](https://arxiv.org/abs/2411.00640).
- The centred README layout follows LiveNerf, which credits [nanochat](https://github.com/karpathy/nanochat).

LiveNerf for Codex is an independent fork.

## Cite

Cite LiveNerf for the original benchmark and LiveNerf for Codex for this
adaptation. Include the run date and results commit when citing a result.

```bibtex
@misc{livenerf,
  author = {{ninjahawk}},
  title = {livenerf: Tracking Post-Launch Capability Drift in Frontier Models},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/ninjahawk/livenerf}
}

@misc{livenerf-for-codex,
  author = {{akmalulkhairin}},
  title = {LiveNerf for Codex},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/akmalulkhairin/livenerf}
}
```

## Licence

[MIT](LICENSE)
