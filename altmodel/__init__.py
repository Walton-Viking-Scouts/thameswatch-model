"""Red-team alternative model + honest evaluation harness for ThamesWatch.

Self-contained experiment package. Does NOT touch the production `tw/` model.
Pure numpy/scipy — no scikit-learn/pandas dependency, so it can run in the same
lean CI as the production model if adopted.

Modules:
  features  — feature engineering (antecedent precipitation index, log flow,
              die-off-weighted CSO load, harmonic seasonality, site effects).
  models    — penalized logistic regression, Platt calibration, baselines.
  evaluate  — forward-chaining temporal CV + leave-one-site-out, asymmetric-cost
              metrics, head-to-head against the production v3 rules.
"""
