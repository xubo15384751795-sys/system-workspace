# Morphology Classifier

## 1. Purpose

Classify stress states by `M/D/K/X` morphology rather than by scalar stress
level alone.

## 2. Inputs

- channel values
- component values
- benchmark context

## 3. Outputs

- morphology label
- leading channel
- rejection or uncertainty notes

## 4. Boundary Rules

- Classification is diagnostic, not a universal crisis detector.
- Case labels require case-page grounding and claim registry alignment.

## 5. Failure Modes

- channel cross-loading
- unstable thresholds
- insufficient case coverage

## 6. Related Code

- `src/diagnostics/morphology_classifier.py`
- `src/diagnostics/structural_diagnostic.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
