# LiveNerf for Codex drift study protocol

This protocol records the Codex adaptation of
[LiveNerf's study design](../PREREGISTRATION.md). It was written during
screening, before confirmation, instrument validation or baseline collection.
The earlier public ten-question monitor remains available as a separate series.

## Models and instrument

Astra is the primary model. Sol is the candidate control and runs on the
GPQA questions from Astra's panel. The study measures GPT-6.2 as served
through the pinned Codex CLI with a dedicated ChatGPT sign-in.

The [instrument](../livenerf/providers/codex/instrument.py) requests an
isolated, read-only thread at an explicit reasoning effort. It excludes
observable reroutes, retries, moderations and turns that fail the result
checks. Codex does not expose all provider-side routing or model identity
details. The study can identify a change in the observed service.

## Screening, confirmation and validation

The source pool uses LiveNerf's pinned GPQA Diamond, MMLU-Pro, competition
math and AIME datasets. Astra runs at high reasoning effort for screening
and confirmation.

1. Screen each question with four scored samples. Stop asking a question
   after two execution errors. A question is eligible when it has both
   a pass and a fail and has no recorded classifier event.
2. Collect eight fresh confirmation scores for each eligible question.
   Use those scores to estimate its pass rate and exclude questions with
   a recorded classifier event during confirmation.
3. Freeze the selected item IDs, content hashes and Sol subset. Publish the
   panel digest, arm sizes and predicted minimum detectable effect before
   starting the drift baseline. Keep the question IDs and logs local.
4. Validate the instrument with four fresh samples per question and arm,
   subject to upstream's per-pair error stop. Astra runs at high, medium
   and low effort. Sol runs at high effort on the shared subset. Apply
   upstream's split-replicate A/A check and the low-versus-high output
   token comparison. Report whether the model swap is distinguishable.
   Settle the control choice before starting the baseline if validation
   fails.

Screening, confirmation and validation samples stay outside the baseline
and the drift analysis.

## Daily series and decision

Attempt one sample per panel question and arm on each UTC day. The first
ten calendar days form the baseline. Subsequent decision windows are
consecutive, non-overlapping ten-day periods. Log missing attempts and
errors so an incomplete window cannot make two separated changes appear
consecutive.

For each closed window, compare each question's mean score with its own
baseline mean. Use the item-clustered standard error. A primary shift must
reach at least three percentage points in the same direction in two
consecutive windows, with both paired 99% confidence intervals excluding
zero. The CLI and study hash must match the baseline. Missing and errored
samples must together account for fewer than 5% of scheduled samples.

If Sol also meets the rule in the same direction, report a shared shift
and leave its cause open. If Sol's comparison is incomplete, leave
attribution open. The public daily 95% intervals describe daily scores.
The paired 99% intervals determine the drift verdict.

## Quota and readiness

The scheduled study has a weekly allowance of 20 percentage points and an
account-wide stop at 50% in any reported window. It counts ambiguous usage
towards the study allowance and leaves headroom for meter lag.

A one-off GPQA screening measurement scored 64 samples while displayed
weekly usage rose by one point. Later manual screening completed two
consecutive 64-sample batches in each of GPQA and MMLU-Pro, with no more than
a one-point rise across either pair. These runs support scheduling up to 128
questions from one of those families per reservation. They leave the exact
cost conversion and the cost of a full Astra and Sol panel open.

The local calibration log records attempts and scores by benchmark family,
alongside the account meter at the start and end of each batch. Use these
records to compare batches from the same family. The meter is account-wide
and can register usage after a batch has finished.

The runner reserves two points per daily run and keeps one point of weekly
headroom. Seven daily reservations and headroom account for 15 points,
leaving five points for observed meter movement in the same window.
The series preflight checks reservation capacity. Before the first baseline
day, the runner checks that the current allowance can cover the planned
daily reservations through the next quota reset. The live meter can still
pause collection if usage exceeds the available allowance.
