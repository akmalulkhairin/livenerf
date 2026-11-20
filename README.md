# LiveNerf for Codex results

Collection ended on 20 November 2026. The [initial comparison](comparison/8ad04dd62da4845f/daily.csv)
and [first baseline day](drift/e4fd3e8126ea3472/daily.csv) record both
78-question runs. The baseline was incomplete when the study ended.
[Study summary](https://github.com/akmalulkhairin/livenerf#study-status)

The chart below records the earlier ten-question monitor.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="daily-dark.svg">
  <img alt="Daily compute scores for Astra and Sol against their own baselines" src="daily.svg">
</picture>

[Daily scores CSV](daily.csv)

## Pilot

[Pilot chart](pilot.svg)

[18 November 2026 pilot scores CSV](pilot.csv)

## Acknowledgements

The Codex study builds on the benchmark and reporting approach by
ninjahawk and the LiveNerf contributors. The test harness uses Inspect,
developed by the UK AI Security Institute and Meridian Labs. OpenAI
provides the Codex CLI and GPT-6.2 models. [LiveNerf](https://github.com/ninjahawk/livenerf) · [Inspect](https://inspect.aisi.org.uk/)

When citing a result, use the run date and the commit from this branch.

## Upstream frozen panel comparison

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="comparison/8ad04dd62da4845f/daily-dark.svg">
  <img alt="Astra and Sol on the same 78 questions" src="comparison/8ad04dd62da4845f/daily.svg">
</picture>

[Scores CSV](comparison/8ad04dd62da4845f/daily.csv) · [Panel, run settings and dated Claude references](comparison/8ad04dd62da4845f/comparison.json)

## Drift study e4fd3e8126ea3472

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="drift/e4fd3e8126ea3472/daily-dark.svg">
  <img alt="Daily scores and baseline progress for the drift study" src="drift/e4fd3e8126ea3472/daily.svg">
</picture>

[Daily scores CSV](drift/e4fd3e8126ea3472/daily.csv)

[Coverage, baseline sensitivity and drift decisions](drift/e4fd3e8126ea3472/study.json)

[Instrument validation and measured sensitivity](drift/e4fd3e8126ea3472/validation.json)

[Frozen panel summary and predicted sensitivity](drift/e4fd3e8126ea3472/design.json)
