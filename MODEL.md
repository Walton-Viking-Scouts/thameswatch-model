# ThamesWatch Model — Technical Reference

A complete description of the water-safety prediction model: its inputs, decision
logic, assumptions, validation results, and known limitations. For a plain-language
overview see [EXEC-SUMMARY.md](EXEC-SUMMARY.md); for how to run it see
[README.md](README.md).

---

## 1. Purpose

The model predicts whether the River Thames is safe for in-water scout activities at
six test sites between Chertsey and Teddington, **without waiting 24-48 hours for a
laboratory E. coli result**. It converts freely available weather, river and sewage
data into a RED / AMBER / GREEN verdict per site.

It is a **decision-support tool**, not a substitute for testing. Its design goal is
asymmetric: never call dangerous water safe, even at the cost of some false alarms.

---

## 2. The verdict scale

| Verdict | Meaning | Action |
|---|---|---|
| 🔴 RED | Water very likely unsafe | Do not go on the water. No exceptions. |
| 🟠 AMBER | Genuinely uncertain | Test with an R-Card before activity; if you can't test, don't go. |
| 🟢 GREEN | Water very likely safe | Go, with standard hygiene precautions. |

"Safe" means E. coli ≤ 500 cfu/100ml — the EU/UK "Excellent" bathing-water threshold
for inland waters. "Dangerous" means E. coli > 2000 cfu/100ml.

---

## 3. Inputs

Each prediction for a site and date uses the following signals. All come from free,
public APIs with no authentication.

| Signal | Description | Source |
|---|---|---|
| `rain_48h` | Rainfall in the prior 48 hours (mm) | EA Hydrology — Hogsmill gauge |
| `rain_7d` | Rainfall in the prior 7 days (mm) | EA Hydrology — Hogsmill gauge |
| `dry_days` | Days since the last rainfall > 2mm (capped at 14) | derived |
| `season` | spring / summer / autumn / winter | derived from the date |
| `cso_active_48h` | Was any relevant storm overflow discharging in the prior 48h? | Thames Water EDM |
| `cso_hours_48h` | Total overflow discharge hours in that window | Thames Water EDM |
| `cso_active_monitors` | Which overflow monitors, and their hours | Thames Water EDM |
| `flow_m3s` | River flow at Walton (m³/s) | EA Hydrology — station 3100TH |
| `upstream_ctx` | Wey / Mole flow, % of total, and surge flags | EA daily mean (levels) + EA flood-monitoring (live surge) — 3090TH / 3290TH |

Rainfall is read from a **single gauge** (Hogsmill, at Kingston) — see §6 for why.
Rainfall runs on the **15-minute** Hydrology series (current to ~1h). Flow is split by
source: the absolute flow value uses the Hydrology **daily mean** (the freshest daily
EA publishes, ~2 days behind), while the live **surge** signal reads 15-minute flow from
the EA **flood-monitoring** API (current to ~1h). The Hydrology *15-minute flow* series
is not used — it is quality-controlled and lags badly (frozen ~2026-04-15 for our gauges).

---

## 4. Decision logic

The model (`tw/model.py`, function `assess_safety`) evaluates a fixed
cascade of rules. The **first rule that matches** sets the verdict — rules are ordered
most-severe first. Each carries a confidence percentage derived from how often that
condition was unsafe in the historical data.

### RED rules (checked first)

| # | Condition | Rationale (historical) |
|---|---|---|
| 1 | CSO active on **2+ relevant river systems** | 0% safe in 34 cases |
| 2 | **4+ CSO monitors** discharging | 0% safe, 67% dangerous |
| 3 | **2-3 CSO monitors** discharging | only 7% safe |
| 4 | `rain_48h` > 10mm | only 5-20% safe |
| 5 | Rained today **and** CSO active | only 11% safe |
| 6 | Rained today (`dry_days` = 0) | only 35% safe |
| 7 | `rain_48h` > 2mm **and** CSO active | only 16% safe |
| 8 | Autumn/winter **and** CSO active | only 10-14% safe |
| 9 | Prolonged CSO (> 50 discharge hours) | only 5% safe |
| 10 | Flow below the site's RED threshold | low flow → no dilution |

### AMBER rules (checked next)

| # | Condition | Rationale |
|---|---|---|
| 11 | `rain_48h` > 2mm | 55% safe — a coin flip |
| 12 | Recent rain (`dry_days` ≤ 2) **and** CSO active | 16% safe |
| 13 | Autumn/winter | only 32% safe even when dry |
| 14 | Recent rain (`dry_days` ≤ 2) | 76% safe but not certain |
| 15 | CSO active (single river) | 33-46% safe |
| 16 | Flow below the site's AMBER threshold | reduced dilution |
| 17 | Tributary **surge** — Wey/Mole rising sharply | upstream rain flushing down |
| 18 | `rain_7d` > 15mm | delayed headwater runoff |
| 19 | Site is **tier 3** (see §5) | elevated baseline — never certified GREEN |

### GREEN rules (only if nothing above matched)

| # | Condition | Confidence |
|---|---|---|
| 20 | `dry_days` ≥ 6, no CSO | 85% |
| 21 | `dry_days` ≥ 3, no CSO | 80% |
| — | otherwise | AMBER (borderline) |

**CSO count vs CSO river-systems** are distinct, both-powerful predictors: the *number*
of monitors discharging (rule 2/3) tracks how heavily the wider catchment was rained on,
independent of *which rivers* are affected (rule 1).

---

## 5. Site-specific design

The single most important finding of the project: a generic all-sites model hid a 16%
false-safe rate, because sites only 200m apart can have completely different risk
profiles. The model is therefore site-specific in three ways.

### Risk tiers

| Tier | Sites | Behaviour |
|---|---|---|
| 1 | Chertsey, Kingston HMT | Reliably clean — can be certified GREEN |
| 2 | Walton Wharf | Mostly reliable — can be certified GREEN |
| 3 | Kingston Albany Reach, Teddington, Ditton's Bend | Elevated baseline — **never GREEN**, AMBER minimum |

Tier 3 sites sit downstream of continuous sewage-works effluent (e.g. Kingston Albany
Reach catches the Hogsmill works outfall) and produce spikes no weather model can
predict. Rule 19 enforces their AMBER floor.

### Site-relevant CSO filtering

A site only considers overflows that are physically upstream of it, so a downstream
overflow never wrongly penalises an upstream site. The monitor set is 16: the 14 along
the Chertsey–Teddington stretch, plus a `ThamesUpstream` system — storm overflows on the
Thames mainstem *above* Chertsey, which sit above the whole stretch and so are relevant
to every site. By geography:

- **Chertsey** is above *both* the Mole and the Wey confluences (the Wey joins downstream
  at Weybridge), so it considers only the `ThamesUpstream` overflows — these are its one
  valid CSO predictor. (Before this was corrected, Chertsey was wrongly keyed to the Wey.)
- **Walton** is below the Wey confluence but above the Mole, so it considers Wey +
  `ThamesUpstream`, and ignores the Mole.
- **Kingston, Teddington and Ditton's Bend** are below both confluences and consider Wey,
  Mole, Thames and `ThamesUpstream`.

The `ThamesUpstream` system is the two monitors nearest Chertsey (Windsor ~5 km, Little
Marlow ~17 km). Three farther overflows were discovered but excluded — see §9.

### Site-specific flow rules

Flow predicts safety **only at Teddington and Ditton's Bend** (RED below 15 m³/s, AMBER
below 20). At Walton flow is *not* used as a dilution signal — counter-intuitively,
higher flow there often means more contamination, because the rise is the polluted Wey
tributary arriving. Flow rules are disabled where the data does not support them.

---

## 6. Key assumptions and design decisions

- **Rainfall from one central gauge.** All sites use the Hogsmill gauge. A per-catchment
  scheme (headwater gauges for each tributary) was built and re-validated — it slightly
  *underperformed* (GREEN 95%→93%). `rain_48h` models *local runoff* at the test site;
  the effect of upstream rain is already captured by river flow and the CSO feed, so a
  central valley gauge beats scattered headwater gauges. See §10.
- **River flow integrates upstream rainfall.** The model needs no network of upstream
  rain gauges — a tributary's flow at its confluence already sums every shower across
  its whole catchment. This keeps the system lean.
- **CSO discharge is the dominant predictor** — 3.4× higher E. coli when active. It is
  weighted accordingly (rules 1-3, 5, 7-9).
- **RED is treated as absolute.** Historically 79-81% of RED conditions were genuinely
  unsafe, and the remaining "false REDs" all had real risk factors (borderline EC
  300-500, never pristine water). RED therefore has no exceptions.
- **Discrete thresholds, not a regression.** Rainfall bands + CSO flags + flow cutoffs
  were chosen over a continuous statistical model — equally accurate on this stretch and
  far more interpretable for non-technical leaders.
- **500 cfu/100ml** is the safe/unsafe boundary (EU/UK "Excellent" inland bathing).
- **The model does not forecast weather.** It assesses conditions that have already
  happened. It is current-state, not predictive of future rain.

### Why the input set is exactly three signals — and not upstream rainfall

The model takes rainfall from one local gauge, flow from the rivers, and discharge
status from the CSO feed. A natural question is whether it should also measure rainfall
across the upstream catchments. It should not — and the reason is timing.

For an upstream rain event the signals become available in a fixed order:

```
upstream rain  →  CSO trips (minutes–1h)  →  flow surge reaches our stretch (~12–18h later)
```

A storm overflow trips on rainfall *intensity* — a short, sharp burst overwhelms the
sewer within minutes. River flow rises from runoff *integrated across the whole
catchment*, which builds far more slowly. This is observed, not assumed: in the
February 2026 Mole event the Esher, Leatherhead and Cobham overflows began discharging
around midday on 15 February while the Mole was still *falling* (8.7 m³/s); the river
did not surge until roughly 12–18 hours later. **The discharge leads the flow surge** —
flow is a lagging, corroborating signal, not a precursor to a discharge.

So each contamination pathway already has the right detector, with no gap and no
redundancy:

| Contamination pathway | Detector | Timeliness |
|---|---|---|
| Upstream rain trips a monitored overflow | CSO discharge feed | Real-time — fires within ~1h of the rain |
| Upstream rain → runoff or an unmonitored spill, no CSO | Tributary flow surge | Caught as the water reaches our stretch |
| Rain on our own stretch | Local rain gauge (Hogsmill) | The heavy-rain rules (4-9) |

The local rain gauge is itself a **primary trigger** — the heavy-rain rules fire on
rainfall directly, before any rise shows in flow. For rain on our own stretch, rainfall
*is* the early signal, and the model already uses it (the Walton 3 September case in §7:
15mm/48h, no CSO, RED from the rain rule).

Measuring *upstream* rainfall, though, would sit in the gap between the first two rows
and add little:

- Against the **CSO feed** it would buy only ~1 hour of lead — negligible against the
  1–3 days the contamination then takes to travel downstream — and it is *less*
  informative. Rainfall alone cannot tell you whether an overflow actually tripped, and
  that distinction is the whole game: runoff alone raises E. coli 10–100×, a CSO raises
  it 100–10,000×. The discharge feed answers it directly; rainfall leaves you guessing.
- Against the **flow surge** it would help in only one narrow case — heavy upstream
  rain that trips *no* monitored overflow — where it would lead the surge by 1–3 days.
  That case is rare, and the flow surge still catches it on arrival; it is recorded as
  an accepted limitation in §9.

Three signals therefore cover the problem well for the current use case — the one
residual gap is rare and non-critical.

---

## 7. Backtesting and validation

The model is validated against `data/thameswatch_correlation_with_cso.csv` — **229 real
ThamesWatch E. coli tests** (2024-03 to 2026-05), each paired with the rain, flow and CSO
conditions on its date. Run `python3 -m tw.model --validate`.

### Overall (v3, 229 samples)

| Verdict | n | Safe (≤500) | Unsafe (>500) | Dangerous (>2000) |
|---|---|---|---|---|
| 🟢 GREEN | 56 | **96%** | 4% | **0%** |
| 🟠 AMBER | 87 | 74% | 26% | 6% |
| 🔴 RED | 86 | 23% | **77%** | 35% |

The headline safety metric — **GREEN but actually unsafe — is 4% (2 of 56), and GREEN
has never once been issued for dangerously contaminated water (0%)**.

### Per-site GREEN performance

| Site | GREEN predictions | Safe |
|---|---|---|
| Chertsey | 5 | 100% |
| Kingston HMT | 10 | 100% |
| Walton Wharf | 41 | 95% |
| Kingston Albany Reach / Teddington / Ditton's Bend | 0 | (tier 3 — never GREEN) |

### Versus the previous model

The current model versus v2.1 (generic): false-safe GREEN predictions fell from **13%
to 4%**, and dangerous-in-GREEN from 1% to 0% — by moving 40+ borderline cases out of
GREEN into AMBER.

### Versus a £5M benchmark

The River Deep Mountain AI project (Cognizant, 65 features, machine learning) does **not**
use CSO discharge data. This 6-input model, because it does, matches RDMAI's accuracy on
the Chertsey-Teddington stretch.

### What the backtest does *not* measure

Validation is single-date: "given conditions on date X, predict EC on X". It cannot
measure *timeliness* — whether a signal is caught earlier. The live 15-minute data
provides that operational gain (a developing tributary surge flags ~2 days sooner than
the daily-mean series would allow); it does not change the validation numbers, and is
not meant to.

---

## 8. Data pipeline

```
EA Hydrology API ─┐
Thames Water API ─┼─→ tw/ package ─→ snapshot ─→ assess_safety ─→ prediction.json
ThamesWatch API ──┘     (fetch + enrich)            (model)         + README block
```

- `tw/config.py` — registry of APIs, stations, CSO monitors, sites.
- `tw/ea_hydrology.py`, `tw/flood_monitoring.py`, `tw/thames_water.py`,
  `tw/thameswatch.py` — API clients.
- `tw/snapshot.py` — assembles every `assess_safety` input for a date, all sites.
- `tw/model.py` — the model itself (`assess_safety`) + the `--validate` gate; run as `python3 -m tw.model`.
- `scripts/predict.py` — runs the model, emits text + `prediction.json` + the README status block.
- A GitHub Action runs `scripts/predict.py` every 3 hours and commits the outputs.

Live freshness by signal: **rainfall** runs on the Hydrology 15-minute series (~1h);
the **absolute flow** value uses the Hydrology daily mean (the freshest daily EA
publishes, ~2 days behind); the live **surge** signal reads 15-minute flow from the EA
flood-monitoring API (~1h) so a developing surge is caught the day it begins. A
staleness guard (`flood_monitoring.MAX_STALENESS_HOURS`) refuses to compute a surge from
a stale feed and falls back to the daily-mean trend, rather than silently using old data.

---

## 9. Limitations and known gaps

- **Two irreducible false GREENs** at Walton (2024-05-21, EC 780; 2025-04-08, EC 600):
  no overflow active on any relevant system and no rain trigger — contamination from
  waterfowl, boat traffic, or steady-state treated effluent concentrated at low flow,
  none predictable from weather, flow or CSO data. This is the floor on GREEN accuracy.
- **Far-upstream Thames overflows add no signal.** Five storm overflows were found on the
  Thames above Chertsey; only the two nearest (Windsor ~5 km, Little Marlow ~17 km) are
  used. In the ablation (`scripts/experiment_upstream_weighting.py`) the three farther ones
  (Reading, Henley, Hambleden — 26–32 km up, beyond ~1–2 days of *E. coli* die-off and
  dilution) caught zero extra unsafe-in-GREEN days while removing seven safe days from
  GREEN — pure false-conservatism, so they are excluded.
- **Tier-3 sites are never GREEN.** Kingston Albany Reach, Teddington and Ditton's Bend
  always require an on-the-day test. The model cannot certify them safe.
- **Flow daily-mean lags.** Absolute flow thresholds (Teddington/Ditton's) run on
  daily-mean flow, which publishes 1-3 days late. When the assessment date's flow is not
  yet available the most recent reading is used and a staleness warning is recorded.
- **Same-day rain is not used.** `rain_48h`/`dry_days` use *prior* days only; rain
  falling on the morning of an afternoon prediction is not yet in the model inputs.
- **Heavy upstream rain that trips no monitored overflow** is caught only when the
  contaminated water reaches our stretch (the flow surge), not 1-3 days earlier when the
  rain falls upstream. Upstream rainfall measurement would close this, but the case is
  rare — the 40+ catchment overflows trip easily — so it is an accepted limitation, not
  worth a rainfall-monitoring network for the current use case.
- **Calibration drift.** The model's thresholds are fixed; as new test data accrues the
  dataset must be refreshed and the model re-validated (see §11).
- **Sparse data at some sites.** Chertsey, Teddington and Ditton's Bend have relatively
  few tests; their per-site figures are less robust than Walton's.
- **AMBER is a coin flip by design** (72% safe). It is an instruction to test, not a
  confident verdict.

---

## 10. How the model evolved

| Version | Change | Result |
|---|---|---|
| v1 | Rainfall + dry-days correlation | First traffic light |
| v2 | Added Thames Water CSO discharge data | CSO found to be the strongest predictor |
| v2.1 | Multi-river CSO early-out rule | Wey+Mole simultaneous = 0% safe |
| v3 | Site tiers, site-relevant CSO, real flow data, CSO count, 7-day rain | False-safe 16%→5% |
| v3.1 | `ThamesUpstream` system (2 nearest Thames-above-Chertsey overflows); Chertsey re-keyed Wey→`ThamesUpstream` | False-safe 5%→4%; Chertsey gains a valid CSO predictor |

**Dead ends** (tried and rejected — do not revisit without new evidence):

- *POOPy package* for CSO data — uninstallable (GDAL/conda); the Thames Water API was
  used directly instead.
- *Generic all-sites model* — hid a 16% false-safe rate; replaced by site tiers.
- *Flow as a universal dilution predictor* — only works at Teddington; at Walton higher
  flow brings more contamination.
- *Per-catchment rain gauges* — built, re-validated, slightly worse than one central
  gauge (see §6).
- *Far-upstream Thames CSO signals* (Reading/Henley/Hambleden, 26–32 km up) — add nothing
  beyond local indicators and only shrink GREEN; excluded. The two *nearest* upstream
  overflows (Windsor, Little Marlow) do help and are kept — see §6 and §9.
- *Teddington level × 400 as a flow proxy* — replaced with real EA flow data.

---

## 11. Maintenance and re-validation

The calibration dataset must be kept current as ThamesWatch publishes new tests.

1. `python3 scripts/fetch_thameswatch.py` — pull the latest raw test results.
2. `python3 scripts/refresh_correlation.py` — append any new results to the dataset.
3. `python3 scripts/rebuild_correlation.py` — recompute the rain enrichment.
4. `python3 -m tw.model --validate` — **the re-validation gate**.

After any dataset change, GREEN must remain ≈95% safe with **0% dangerous**. If accuracy
degrades materially, a change is wrong — investigate before deploying. Keep a backup of
the previous dataset so any change is reversible.
