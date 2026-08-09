# ThamesWatch — Independent Red-Team Review

_2026-06-11 · an adversarial, evidence-based review of the v3.2 water-safety model,
with a working alternative model and an honest out-of-sample re-validation._

This is a challenge document. It exists to find where the current model is weaker than
it looks, to test genuinely different approaches, and to recommend only changes that
earn their place. Where the current model is right, it says so — and it is right about a
lot. The code backing every number here is in [`altmodel/`](../altmodel/); rerun it with
`python3 -m altmodel.evaluate` and `python3 -m altmodel.experiments`.

---

## TL;DR

1. **The headline "GREEN is safe 93% of the time" is an in-sample number.** The v3 rules
   were hand-tuned by looking at the same 239 tests they are then scored against. Under
   proper out-of-sample evaluation, a from-scratch model trained the same way lands at
   **~12–15% false-safe, not 7%.** The model is good, but the brochure figure is
   optimistic by roughly 2×. Budget for the higher number.

2. **On its current inputs, the model is near its ceiling.** A calibrated logistic
   regression — a genuinely different method — ties the hand-tuned rules and does not beat
   them on the safety metric. This is itself the finding: the rules are well-built, and
   the remaining error is *not* an algorithm problem.

3. **The real ceiling is dry-weather spikes.** 27 of the 93 unsafe results (**29%**) had
   neither meaningful rain nor any CSO discharge. No rain/CSO/flow model can see these.
   The current model "handles" 21 of them only by *refusing to ever certify GREEN* at the
   elevated sites — blanket caution, not prediction. That is safe but blunt, and it is why
   the Tier-3 sites are permanently AMBER and carry almost no information.

4. **The only way to materially do better is new signal, not a better model.** Water
   temperature, a low-flow concentration term, and — the big one — the **EA's new
   designated bathing water at Ham & Kingston (inside the stretch, designated 2026)** with
   weekly lab E. coli + enterococci and the EA's own pollution-risk forecast.

5. **Forecasting is viable and cheap.** Dropping the same-day CSO feed (forecast mode)
   costs almost nothing (AUC 0.84 → 0.83), because CSO discharge is itself rain-driven and
   rainfall is forecastable. A day-ahead "plan your session" forecast is within reach.

6. **A probability model is worth adopting even at equal accuracy** — for honesty
   (calibrated %), a tunable risk dial, principled handling of the two un-calibrated sites,
   and forecasting. Not because it is more accurate today.

---

## 1. What the current model gets right (credit first)

A red team that only attacks is useless. The v3 model is a genuinely strong piece of work:

- **It crushes the honest baseline.** The floor every nowcast must beat is *persistence*
  ("it was bad last time, assume it still is"). Persistence runs **28% false-safe** out of
  sample; the model is far better. It has real, demonstrable skill — this is not a
  glorified coin flip.
- **CSO discharge really is the dominant single predictor** (univariate AUC 0.89 vs 0.76
  for rain). The decision to centre the model on the Thames Water EDM feed was correct and
  evidence-backed.
- **Site-specificity was the right call.** The univariate and multivariate analyses both
  confirm large, real per-site differences. The "generic model hid a 16% false-safe rate"
  story holds up.
- **The asymmetric design instinct is correct** — never call dangerous water safe, eat the
  false alarms. The model has never put GREEN on dangerous water in the record, in-sample
  *or* out. That discipline is the most important thing and it must be preserved.
- **The single-gauge and far-upstream-CSO ablations were done properly.** Those "dead
  ends" are real dead ends; this review does not reopen them.

Keep all of the above. The criticisms below are about *calibration of confidence* and
*where the next gain comes from*, not about tearing this down.

---

## 2. Finding 1 — the 7% is in-sample; the honest number is ~12–15%

The production `--validate` trains and tests on the same 239 rows. The rules' thresholds
("rain_48h > 10", "dry_days ≥ 6", the per-site tiers) were chosen by eyeballing those
exact points, so the reported per-bin accuracy is optimistic by construction. This is the
single most important methodological issue, and the external literature is blunt about it:
a small-sample model reporting high accuracy on its own training data "should be treated
as unvalidated until it demonstrates skill on held-out time blocks against a persistence
baseline" (USGS / EPA Virtual Beach doctrine; the Cognizant **River Deep Mountain AI**
project hit exactly this wall and documented it).

I rebuilt the evaluation to be out-of-sample two ways:

- **Forward-chaining (expanding window):** sort by date, train only on the past, predict
  the next block, roll forward. This is the operational reality of a live forecaster.
- **Leave-one-site-out:** train on five sites, predict the sixth — tests geographic
  transfer (RDMAI's documented failure mode).

Head-to-head, pooled out-of-sample (`python3 -m altmodel.evaluate`):

| Method | GREEN issued | False-safe in GREEN | Dangerous in GREEN | Sensitivity (unsafe caught) | Mean cost* |
|---|---|---|---|---|---|
| Persistence (floor) | 95/130 | **28%** | 7 | 44% | 2.40 |
| Rainfall threshold | 0/130 | – | 0 | 100% | 1.19 |
| **v3 rules (in-sample, full set)** | 59/239 | **7%** | 0 | 96% | 0.92 |
| v3 rules (on the OOS rows; still in-sample-tuned) | 33/130 | **9%** | 0 | 94% | 0.99 |
| **New logistic (true OOS)** | 24/130 | **12%** | 0 | 94% | 1.05 |
| New logistic (leave-one-site-out) | 81/239 | **14%** | 1 | 88% | 1.11 |

<sub>*Mean cost uses an explicit asymmetric matrix: false-GREEN-on-unsafe = 10, RED-on-safe
= 3, AMBER-on-safe = 1, AMBER-on-unsafe = 2, correct = 0. Exposed and tunable in
`altmodel/evaluate.py`.</sub>

The honest reading: the **true false-safe rate of a model built this way is ~12–15%, not
7%.** The 7% isn't a lie — it's what in-sample fitting always reports. The fix is not
necessarily a different model; it is to **state the out-of-sample number** in MODEL.md and
README, and to add a persistence baseline to `--validate` so the model must keep beating
it as data accrues. Crucially, the **0% dangerous-in-GREEN guarantee survives out of
sample** — that, not the 7%, is the claim worth advertising.

---

## 3. Finding 2 — on these inputs, the model is at its ceiling

A calibrated penalized logistic regression (pure numpy/scipy, no new dependencies — see
§7) was trained on engineered features: a decayed antecedent-precipitation index, log
flow, a die-off-weighted CSO load, harmonic seasonality, and per-site effects. Out of
sample it scores **AUC 0.84, PR-AUC 0.85** — strong discrimination — but on the safety
metric it **ties the hand-tuned rules; it does not beat them** (12% vs 9% false-safe, well
within the noise of 130 test points).

This matches the strongest meta-finding from the literature review: for this problem class
*the algorithm is nearly interchangeable; the threshold, the cost weighting, and honest
validation are where models live or die.* You cannot ML your way past the information in
the inputs, and the inputs are already being used well.

So the case for a new model is **not accuracy**. It is everything else in §6.

---

## 4. Finding 3 — the real ceiling is dry-weather spikes (the most important result)

Break the 93 unsafe results down by what signal preceded them:

| Unsafe events preceded by… | Count | Share |
|---|---|---|
| Active CSO discharge | 57 | 61% |
| Rain > 2mm (no CSO) | 9 | 10% |
| **Neither rain nor CSO — dry-weather spikes** | **27** | **29%** |

**Nearly a third of all unsafe events are invisible to the entire rain + CSO paradigm.**
They span every season and four of the six sites (Walton, Kingston Albany, Teddington,
Ditton's Bend), with E. coli up to 3,600. Causes are off-model: continuous sewage-works
effluent (the Hogsmill works at Albany), waterfowl, boat traffic, leaf-fall, and low-flow
concentration on warm days.

How does the current model fare on these 27? It calls **4 GREEN (the known false-safes),
21 AMBER, 2 RED.** But the 21 AMBERs are *not predictions* — they are the Tier-3 blanket
floor firing. The model is not seeing the spike; it is refusing to certify GREEN at those
sites at all, ever. That is safe, but it means:

- the elevated sites are **permanently AMBER**, so the signal there carries no information
  ("test first" every single day is the same as having no model);
- the model's apparent safety on dry spikes is **bought entirely with GREEN-volume** — it
  is conservative, not clairvoyant;
- MODEL.md frames this as "4 spring Walton false-GREENs," which undersells it. The real
  blind spot is **27 events / 29% of all unsafe days**, only kept off the GREEN list by
  never offering GREEN where they happen.

This is the single highest-value thing the review surfaces: **the model is not rain-limited
or CSO-limited or algorithm-limited. It is signal-limited on dry-weather contamination.**
No reweighting of rain and CSO will fix it. Only new measurement will (§6).

---

## 5. Finding 4 — what actually drives the model (ablation accounting)

Out-of-sample ablations (`python3 -m altmodel.experiments`), read off the threshold-
independent AUC:

| Configuration | OOS AUC | Note |
|---|---|---|
| Full feature set | 0.84 | |
| CSO + rain + seasonality only | 0.85 | **as good as full** |
| Drop seasonality (sin/cos DOY) | **0.76** | biggest single loss |
| Drop the decayed precip index (API) | 0.85 | **API earns nothing** |
| Drop flow (log flow + surge) | 0.84 | flow earns ~nothing pooled |
| Rain + season + site only (no CSO, no flow) | 0.83 | |

Takeaways:

- **The model is essentially CSO + rainfall + seasonality.** Everything else is rounding.
- **Continuous seasonality is the most under-exploited signal.** The production model uses
  season only as a coarse "autumn/winter" flag in two rules; a smooth sin/cos harmonic of
  day-of-year is worth ~0.08 AUC — more than flow and the API combined. This is a cheap,
  high-value change: replace the binary season flag with a day-of-year term.
- **The fancy decayed antecedent-precipitation index does not help here.** I built it
  because the literature favours it; on this data it is collinear with `rain_48h` +
  `dry_days` + season and adds nothing. An honest negative result — don't bother.
- **Flow barely matters pooled**, consistent with the production note that flow only helps
  at Teddington/Ditton's. But note `log_flow` has univariate AUC 0.67 and a *positive*
  coefficient (higher flow → higher risk overall), echoing the Walton "Wey brings
  contamination" effect. A **low-flow concentration term** is worth testing specifically
  for the dry-weather spikes (§6), which is different from flow-as-dilution.

---

## 6. Finding 5 — the only path past the ceiling is new data

Because §4 shows the ceiling is dry-weather signal, the highest-leverage work is data
acquisition, not modelling. Ranked by payoff (full endpoint detail in the companion data
brief; all free / low-cost, no-auth unless noted):

1. **EA Bathing Water Quality API — "Thames at Ham & Kingston" (designated 2026).** A
   designated bathing water *inside the stretch*, just above Teddington, with weekly lab
   **E. coli + intestinal enterococci** and the **EA's own pollution-risk forecast**. This
   is independent ground truth and a second modelled opinion, free. It is the single most
   valuable integration. `https://environment.data.gov.uk/bwq/` (in-season May 15–Sep 30;
   needs an off-season story). It directly attacks the dry-weather blind spot because it is
   *measurement*, not inference.

2. **Water temperature** (already in the ThamesWatch raw feed — `waterTemperature`, but
   only 62/286 populated, and unused). Temperature governs bacterial die-off *and* warm-
   low-flow growth, which is the likely mechanism behind the summer Kingston-Albany spikes.
   Backfill it from Open-Meteo and make it a feature. Cheap.

3. **A low-flow concentration term.** Many dry spikes coincide with low flow (continuous
   effluent diluted by less water). `log_flow` already shows signal; an explicit
   `effluent / flow` style term, per Tier-3 site, is the most plausible *model-only* lever
   on the dry-weather problem. Test it before reaching for new sensors.

4. **Open-Meteo precipitation forecast (UK Met Office 2 km model) + `minutely_15`
   nowcast.** The driver for day-ahead forecasting (§ next). Free; note the non-commercial
   licence if this ever goes public-facing.

5. **Thames Water `DischargeAlerts` history** (spill start/stop events back to 2022).
   Enables a proper die-off-weighted spill kernel with real event timing — the version of
   the CSO feature I could only approximate here because the calibration CSV stores 48h
   totals, not per-spill timing.

6. **Enterococci as a second indicator.** The raw feed has `ei` (176/286). The EU directive
   treats intestinal enterococci as the stricter inland health indicator. A two-indicator
   model (predict the worse of the two) is more health-conservative than E. coli alone.

7. **EA real-time turbidity/quality sondes**, *if* one is sited near Kingston/Teddington —
   turbidity is the single strongest predictor in US beach nowcasts. Verify coverage before
   relying on it.

---

## 7. The alternative model — what it is and why adopt it (despite equal accuracy)

`altmodel/` contains a complete, runnable alternative: an **L2-penalized logistic
regression** producing a **calibrated probability of "unsafe (EC > 500)"**, mapped to
RED / AMBER / GREEN by **two cost-tuned thresholds**. It is pure numpy/scipy — it adds *no*
dependency to the lean CI that runs every 3 hours. Reasons to adopt it even though it does
not beat the rules on accuracy:

- **It outputs a number, not just a colour.** "68% chance unsafe" is more actionable for a
  leader deciding whether to test than an opaque AMBER, and it makes the model's confidence
  honest and inspectable.
- **It exposes the risk dial.** The single most-recommended lever in the literature is
  "tune the decision threshold below 0.5 against the cost of a miss." With rules that lever
  is buried in a dozen hand-set constants; with a probability + threshold it is one number
  the user can own. (Caveat from the sweep: at 130 OOS points the optimum is noisy —
  set it by policy, e.g. "GREEN only below 15% modelled risk," not by chasing the data.)
- **It handles the two un-calibrated sites principledly.** Hogsmill confluence and Minima
  currently get a hard-coded Tier-3 floor by geography alone. The shared model with site
  effects transfers to unseen sites at **AUC 0.83 (leave-one-site-out)** — it can give them
  a real estimate from geography + shared physics instead of a blanket guess.
- **It forecasts.** Rules assess the present; a probability driven by *forecast* rainfall
  predicts the future. See below.
- **It self-recalibrates** as data accrues (refit, don't re-eyeball), and it carries a
  persistence baseline as a permanent honesty check.

What it is **not**: more accurate on today's inputs (§3), and not a reason to throw away
the rules' interpretability. The pragmatic recommendation is a **hybrid**: keep the rule
cascade as the explainable safety spine (especially the absolute RED rules and the 0%-
dangerous-in-GREEN guarantee), and run the logistic alongside to supply the probability,
the tunable GREEN threshold, the un-calibrated-site estimates, and the forecast.

---

## 8. Forecasting — viable, and cheaper than expected

The model is deliberately current-state. But the forecast-mode experiment shows the cost of
going a day ahead is small:

| Mode | Inputs | OOS AUC | False-safe |
|---|---|---|---|
| Nowcast (full, same-day) | rain + CSO + flow + season + site | 0.84 | 12% |
| **Forecast (day-ahead-knowable)** | rain + season + site, **no same-day CSO/flow** | **0.83** | 13% |

The reason it barely degrades: **CSO discharge is itself rain-driven, and rainfall is
forecastable.** You lose little by predicting the spill risk from forecast rain instead of
reading the live spill feed. A practical architecture:

1. Pull tomorrow's hourly precipitation (Open-Meteo UK 2 km) → build tomorrow's `rain_48h`
   / antecedent terms.
2. Feed forecast rain + season + site into the logistic → **tomorrow's risk probability.**
3. Keep today's live CSO + flow as a same-day *override* (if a spill is active now, don't
   downgrade on a dry forecast).
4. Validate honestly against the **Open-Meteo Historical Forecast API** (archived past
   forecasts), so the backtest sees real forecast error, not perfect hindsight.

This turns the tool from "is it safe right now" into "should we plan Saturday's session" —
a materially more useful product for scout leaders, who schedule ahead. It is the one place
where "different" is clearly "better."

---

## 9. Confirmed dead ends (do not reopen)

The review independently re-confirms the existing rejections, and adds two:

- Per-catchment rain gauges — still worse than the single central gauge.
- Far-upstream Thames CSOs (Reading/Henley/Hambleden) — still pure false-conservatism.
- Flow as a universal dilution predictor — confirmed; pooled flow adds ~nothing.
- **(new) The decayed antecedent-precipitation index** — theoretically attractive, empirically
  useless here; collinear with the rain/dry-days/season already present.
- **(new) Swapping the rule cascade for an ML model to gain accuracy** — it does not gain
  accuracy. Adopt a probability model for the *other* reasons (§7), or not at all.

---

## 10. Recommendations, ranked by payoff ÷ effort

**Do now (cheap, high-value, no new data):**
1. **Report the out-of-sample number.** Add persistence + forward-chaining to
   `--validate`; state ~12–15% false-safe alongside the in-sample 7%. Advertise the
   0%-dangerous-in-GREEN guarantee (it survives OOS) as the real headline. _(½ day)_
2. **Replace the binary season flag with a continuous day-of-year harmonic.** Biggest cheap
   accuracy lever found (~0.08 AUC). _(½ day)_
3. **Add a low-flow concentration term at the Tier-3 sites** and test it against the dry-
   weather spikes specifically. _(1 day)_

**Do next (the real gains):**
4. **Integrate the EA Ham & Kingston bathing-water feed** as ground truth + second opinion;
   start logging it now to build an off-season-aware record. _(2–3 days)_
5. **Backfill and use water temperature**; add **enterococci** as a second, stricter
   indicator. _(2 days)_
6. **Stand up the logistic as a companion** to the rules (probability + tunable GREEN
   threshold + un-calibrated-site estimates). Ship `altmodel/` behind the existing model.
   _(2–3 days)_

**Do when ready (new capability):**
7. **Day-ahead forecasting** via Open-Meteo, validated on archived forecasts. The biggest
   product upgrade. _(1 week)_
8. **Die-off-weighted spill feature** from Thames Water `DischargeAlerts` event timing.
   _(3 days)_

**Never:**
9. Don't chase a fancier algorithm for accuracy on the current inputs. The ceiling is
   signal, not method (§3–4).

---

## 11. One model, per-site models, or partial pooling? (follow-up)

A natural challenge: the pooled model forces one shared rain/CSO/flow slope on every site,
yet Walton (109 tests, 46% of the data) demonstrably behaves differently. Should Walton be
standalone? Tested three architectures out-of-sample (`altmodel/walton_standalone.py`,
`altmodel/partial_pool.py`):

| On Walton's 66 OOS tests | GREENs | False-safe | AUC |
|---|---|---|---|
| Pooled (shared slopes + site dummy) | 7 | **0%** | 0.87 |
| Partial-pooled (site-specific slopes, shrunk) | 16 | 19% | 0.87 |
| Standalone Walton (own slopes) | 21 | 19% | 0.84 |

**All three have the same ranking ability (AUC ≈ 0.87); they differ only in conservatism.**
Standalone and partial pooling issue more GREENs but every one of the extra GREENs risks a
dry-weather spike (§4), so they pick up false-safes the conservative pooled model avoids.
Per-site modelling does **not** beat pooling here — 109 tests is still too few to fit free
slopes, and the gain there would be on inputs that are blind to the binding error anyway.

Partial pooling is still worth adopting, for *structure* not accuracy: it is the principled
replacement for the hard-coded Tier 1/2/3 system. Data-rich sites specialize, data-poor and
un-calibrated sites (Chertsey n=15, Teddington n=13, Hogsmill confluence, Minima) auto-shrink
to the shared model in one fit — no manual tiers. Notably it independently shrinks Walton's
overfit standalone flow slope (−0.41) back to ~neutral (+0.07), confirming the production
"flow doesn't predict at Walton" call and rejecting MODEL.md's stronger "higher flow → more
contamination" claim. This is the third independent route to the same conclusion: **the
ceiling is signal, not model structure.** The Walton lever is new measurement (temperature,
a low-flow term, the EA Ham sampling point) plus a dry-window testing cadence — not a
per-site equation.

## Appendix — how to reproduce

```bash
# Honest head-to-head: in-sample rules vs OOS baselines vs OOS logistic + LOSO
python3 -m altmodel.evaluate

# Asymmetric-cost sweep, feature ablations, forecast-mode
python3 -m altmodel.experiments

# Site architecture: Walton standalone vs pooled; partial-pooling sweep (§11)
python3 -m altmodel.walton_standalone
python3 -m altmodel.partial_pool
```

`altmodel/` is self-contained (numpy + scipy, both already in the repo). It never imports
or mutates the production `tw/` model except to *read* its v3 rules for the comparison, so
the live every-3-hours prediction is untouched. The cost matrix, feature set, and CV
parameters are all near the top of their modules and are meant to be edited.

_Reviewer's note: the strongest thing about this project is the safety discipline — RED is
absolute and GREEN has never covered dangerous water. Everything above is written to
protect that property while making the confidence honest and the GREENs rarer-but-truer.
The model isn't broken. It's near the limit of what rain and sewage data can tell you, and
the next real gain is a thermometer and the EA's new sampling point at Ham, not a cleverer
equation._
