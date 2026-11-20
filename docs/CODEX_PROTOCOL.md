# LiveNerf for Codex drift study

The study uses [LiveNerf's frozen panel](adr/0002-use-the-upstream-frozen-panel.md)
and its [baseline and decision procedure](../PREREGISTRATION.md). Astra is the
primary model. Sol is the control and answers all 78 questions alongside
Astra. Both use high reasoning effort in the daily series.

The [Codex instrument](../livenerf/providers/codex/instrument.py) uses a pinned
CLI and a dedicated ChatGPT sign-in. Each question runs in an isolated,
read-only thread. The instrument rejects observable reroutes, retries,
moderations and turns that fail its result checks. The study measures the
observed service. Some provider-side routing and model identity details are
unavailable through Codex.

## Before the baseline

1. Verify the upstream revision, question contents, prompt and graders.
   Publish the panel digest and predicted sensitivity. The prediction assumes
   independent samples and a 50% pass probability per question, which gives
   the largest binary-score variance in the planning calculation. Both models
   use the same panel, so they have the same predicted sensitivity under
   those assumptions.
2. Collect four fresh scores for every question in each of four arms. Run
   Astra at high, medium and low effort and Sol at high effort. Use the
   upstream per-pair error stop. The split-replicate A/A check tests whether
   two sets of Astra high-effort runs give consistent results. The low-effort
   comparison checks that its 99% interval for the change in output tokens
   excludes zero.
3. Publish the validation results before baseline collection. The baseline
   requires four graded scores for each question and arm and a pass on both
   checks. Report the accuracy and output-token differences for each effort
   and for the Astra-to-Sol model swap, with their 99% confidence intervals.
   These differences show what the current setup can detect in validation.

The initial comparison, the archived Astra calibration and the validation
runs have separate logs and contribute zero samples to the drift baseline.

## Daily series and decision

The workstation timer runs at 00:20 UTC (08:20 Malaysia time). The first UTC
day admitted by the budget starts the ten-calendar-day baseline. Attempt one
sample per question and model on each UTC day. A run interrupted after
admission keeps that date in the calendar. Later decision windows are
consecutive ten-day periods. The report preserves missing dates and errors.

For each closed window, compare each question's mean score with its baseline
mean and use the item-clustered standard error. A primary shift must reach at
least three percentage points in the same direction in two consecutive
windows, with both paired 99% confidence intervals excluding zero. The CLI
and study identity must match the baseline. Missing and errored samples
must account for fewer than 5% of scheduled samples in each relevant window.

A matching change in Sol gives a shared shift with no assigned cause. An
incomplete Sol comparison leaves attribution open. The 95% intervals on
the chart describe daily scores. The paired 99% intervals govern the drift
decision. The results include measured baseline sensitivity once the
baseline closes with sufficient coverage.

## Quota and operation

Scheduled validation and daily runs share a 20-point weekly study allowance.
The account-wide stop is 50% in any reported window. The runner checks the
live account meter before each sample. Each validation batch of up to 156
attempts or each admitted daily run reserves two points in the study ledger.
The ledger also counts observed account usage above its start value and keeps
one point of headroom. Seven daily reservations and headroom leave five
points for observed meter movement. This is a reservation calculation. Daily
run costs depend on measured usage across a full week.

Set `LIVENERF_STUDY_ALLOWANCE` to `reset_timestamp:points` in the scheduled
service to raise the ledger allowance for one confirmed weekly window. Use
`reset_timestamp:off` to suspend the ledger cap for that window. The ledger
continues recording reservations and usage. The next window uses the normal
cap. Use `off` on its own when measuring usage across quota windows. The
account-wide stop applies throughout.

The workstation saves the weekly account meter before and after each invocation
that records daily series attempts. Use at least five complete UTC days with
results for both models before estimating a weekly budget. The account meter
includes other Codex activity and may update after a benchmark finishes.

`uv run --locked python -m livenerf.codex_upstream_study` verifies the panel
and shows validation progress. Pass `--prepare` to freeze and publish the
design without submitting a benchmark question. The
[workstation timer](../scripts/systemd/livenerf-codex-drift.timer) invokes the
runner to advance validation or collect the current UTC day.

The [original decision record](adr/0001-use-livenerf-protocol-for-codex-drift-study.md)
describes the earlier Astra-specific calibration. The
[panel decision](adr/0002-use-the-upstream-frozen-panel.md) records the switch
to the upstream questions and dates the first comparison separately.
