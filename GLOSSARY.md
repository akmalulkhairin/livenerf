# LiveNerf for Codex

LiveNerf for Codex studies changes in GPT performance as served through
the Codex CLI.

## Language

**Daily monitoring**:
The fixed public compute series that records scores and shows them
against each model's own reference score.

**Drift study**:
A benchmark calibrated for the measured model and evaluated against
pre-registered criteria for a sustained change.

**Protocol parity**:
Using LiveNerf's calibration, baseline and decision procedure for the
Codex drift study, with the panel calibrated for the model under study.

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
