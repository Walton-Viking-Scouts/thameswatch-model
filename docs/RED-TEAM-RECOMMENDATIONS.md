# ThamesWatch — Red-Team Recommendations & Implementation Roadmap

_2026-06-11 · decisions and a phased plan arising from the independent review in
[`RED-TEAM-2026-06.md`](./RED-TEAM-2026-06.md). This is the "what to do" companion to that
"what we found" document. Nothing here is implemented yet — it is a backlog to pick from._

---

## The headline decision

**Do NOT replace the production rule cascade with the new logistic model.**

The review built a full alternative (calibrated logistic regression, partial-pooling
variants — all in [`altmodel/`](../altmodel/)) and evaluated it honestly out-of-sample. It
**ties the hand-tuned rules and beats them nowhere on accuracy.** The rules are
interpretable, well-built, and carry the most important property — GREEN has never covered
dangerous water, in-sample or out. Swapping a working model for an equal-accuracy one is
risk with no payoff, and fails the project's own bar ("different for different's sake is
not").

What the review *does* justify: harvest the cheap fixes, run the new model as a **shadow
companion** (never the decider, at first), build **forecasting** (the one thing rules
cannot do), and pursue **new data** (the only path past the real ceiling). Trust shifts to
the model only if a live shadow comparison and new data prove it earns it.

### Why (one line each)
- The advertised "7% false-safe in GREEN" is in-sample; honest out-of-sample is ~12–15%.
- On current inputs the model is at its information ceiling — algorithm choice barely matters.
- 29% of all unsafe events are dry-weather spikes invisible to every rain/CSO/flow model.
- Per-site / partial-pooling models don't beat the simple pooled model — the ceiling is
  signal, not model structure.
- The only material gains are new measurement (temperature, low-flow term, EA Ham sampling)
  and a day-ahead forecast.

---

## Phased backlog

Pick top-down; each phase is independent and reversible. Effort is rough solo-dev time.

### Phase 1 — Honesty & cheap accuracy (no new model) — ~1 day
- [ ] **Add a persistence baseline + forward-chaining OOS to `tw/model.py --validate`.**
      Port the harness from `altmodel/evaluate.py`. The model must keep beating "it was bad
      last time" as data accrues.
- [ ] **State the out-of-sample number** (~12–15% false-safe) next to the in-sample 7% in
      `MODEL.md` and `README.md`. Make the surviving **0% dangerous-in-GREEN** the headline.
- [ ] **Replace the binary autumn/winter season flag with a continuous day-of-year harmonic**
      (`sin/cos(2π·doy/365)`). Biggest cheap accuracy lever found (~0.08 AUC); slots into the
      existing rule logic.

### Phase 2 — Shadow-deploy the new model as a companion — ~3 days
- [ ] **Run `altmodel/` alongside the rules** in the 3-hourly job. Emit its calibrated
      probability of "unsafe" into `prediction.json` **next to** the rule colour. **Rules
      still decide the verdict.** Zero-risk; lets a "68% chance unsafe" reach leaders and
      lets you A/B model-vs-rules live for a season.
- [ ] **Adopt the partial-pooling fit** (`altmodel/partial_pool.py`) so the data-poor and
      un-calibrated sites (Chertsey, Teddington, Hogsmill confluence, Minima) auto-shrink to
      the shared model — retires the manual Tier 1/2/3 assignments.
- [ ] **Expose the risk dial**: GREEN only below an explicit modelled-risk policy (e.g. 15%),
      set by policy not by chasing the small-sample optimum.

### Phase 3 — Forecasting (new capability the rules cannot do) — ~1 week
- [ ] Pull tomorrow's hourly precipitation (Open-Meteo, UK Met Office 2 km model) → build
      tomorrow's antecedent-rain features.
- [ ] Feed forecast rain + season + site into the logistic → **tomorrow's risk probability**
      ("should we plan Saturday's session"). Forecast mode loses almost nothing vs nowcast
      (AUC 0.84 → 0.83) because CSO discharge is itself rain-driven.
- [ ] Keep today's live CSO/flow as a same-day override (don't downgrade on a dry forecast
      if a spill is active now).
- [ ] **Validate on the Open-Meteo Historical Forecast API** (archived past forecasts) so the
      backtest sees real forecast error, not perfect hindsight.

### Phase 4 — New signal: the real ceiling-breaker (parallel track) — ongoing
- [ ] **Start logging the EA Bathing Water Quality feed for "Thames at Ham & Kingston"**
      (designated 2026, inside the stretch). Weekly lab E. coli + enterococci + EA's own
      pollution-risk forecast. Independent ground truth + a second opinion. Build the record
      now; needs an off-season strategy (in-season May 15–Sep 30).
- [ ] **Backfill water temperature** (Open-Meteo) and make it a feature — governs die-off and
      warm-low-flow growth (likely mechanism behind summer Kingston-Albany spikes).
- [ ] **Add a low-flow concentration term** at the Tier-3 sites; test specifically against the
      dry-weather spikes.
- [ ] **Add enterococci (`ei`) as a second, stricter indicator** (predict the worse of E. coli
      / enterococci).
- [ ] **Die-off-weighted spill feature** from Thames Water `DischargeAlerts` event timing
      (back to 2022) — replaces the 48h-total approximation.
- [ ] For Walton specifically: a standing **physical testing cadence in the spring/early-autumn
      low-flow windows**, where the model is provably blind. Model where you can predict;
      measure where you can't.

### Never
- [ ] Don't swap the rules for an ML model to gain accuracy — it doesn't (Phase-0 finding).
- [ ] Don't reopen the confirmed dead ends: per-catchment rain gauges, far-upstream Thames
      CSOs, flow-as-universal-dilution, the decayed antecedent-precipitation index (collinear,
      adds nothing), per-site standalone models (overfit; don't beat pooling).

---

## Artefacts produced by the review (already in the repo)

| Path | What |
|---|---|
| [`docs/RED-TEAM-2026-06.md`](./RED-TEAM-2026-06.md) | Full analysis: findings, head-to-head, data-source brief, §11 site-architecture follow-up |
| `altmodel/features.py` | Feature engineering (API rainfall, log flow, die-off CSO load, harmonic seasonality, site effects) |
| `altmodel/models.py` | Pure numpy/scipy penalized logistic + per-column-penalty ridge + baselines |
| `altmodel/evaluate.py` | Honest OOS harness (forward-chaining + leave-one-site-out, asymmetric cost) — `python3 -m altmodel.evaluate` |
| `altmodel/experiments.py` | pos_weight sweep, ablations, forecast-mode — `python3 -m altmodel.experiments` |
| `altmodel/walton_standalone.py` | Walton standalone vs pooled — `python3 -m altmodel.walton_standalone` |
| `altmodel/partial_pool.py` | Partial-pooling sweep — `python3 -m altmodel.partial_pool` |

`altmodel/` is self-contained (numpy + scipy only) and never mutates the production `tw/`
model — the live 3-hourly prediction is untouched.
