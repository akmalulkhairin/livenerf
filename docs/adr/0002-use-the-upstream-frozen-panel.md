# Use the upstream frozen panel for Codex model comparisons

Run GPT-6.2 Astra and Sol on all 78 questions in
[LiveNerf's frozen panel](https://github.com/ninjahawk/livenerf/blob/52ca4d9/data/standard_panel.json)
with the upstream graders. This gives each model a score on the same
questions that Opus 5.5 and Fable 5.2 answered. The daily comparison
requires 156 responses.

Use the published Opus and Fable scores as dated references. Retain their
original run dates, CLI versions and effort settings so readers can see
the conditions under which each score was collected.

Publish the first complete pair of runs as an initial comparison. Start the
formal baseline after validating the Codex instrument and the panel's drift
sensitivity. Pause the Astra-specific calibration and retain its saved data.
Archive the ten-question monitor once the shared-panel chart is public.
