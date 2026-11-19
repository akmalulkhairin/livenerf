# LiveNerf for Codex

LiveNerf for Codex studies changes in GPT performance as served through
the Codex CLI.

## Language

**Daily monitoring**:
The fixed public compute series that records scores and shows them
against each model's own reference score.

**Drift study**:
A series of repeated runs on a fixed panel, evaluated against
pre-registered criteria for a sustained change.

**Protocol parity**:
Using LiveNerf's sampling, baseline and decision procedure for the
Codex drift study.

**Upstream frozen panel**:
The 78 questions LiveNerf fixed for its Opus 5.5 series. Fable 5.2 uses
the same questions and graders.

**Shared-panel comparison**:
A comparison of scores from models that answered the upstream frozen
panel and were graded by the same rules.

**Claude reference scores**:
The published Opus 5.5 and Fable 5.2 scores on the upstream frozen panel,
with their original run dates and settings.

**Primary model**:
The model to which the drift study's main conclusion applies.

**Control arm**:
Runs on a second model over a shared set of questions, used to check whether
a shift also appears outside the primary model.

**Study budget**:
The share of weekly Codex allowance reserved for benchmark work, including
calibration.

**Account-wide stop**:
The total account usage threshold above which the study pauses.
