# ThamesWatch — water-safety prediction

A traffic-light model that predicts whether the River Thames is safe for water
activities at the Walton Viking Sea Scouts' stretch — **before** you get to the water,
without waiting 24-48h for a lab result.

It checks rainfall, river flow, and sewage-discharge conditions and returns a
**RED / AMBER / GREEN** verdict for each test site:

- 🔴 **RED** — Enhanced precautions.
- 🟠 **AMBER** — Increased precautions.
- 🟢 **GREEN** — Normal precautions.

<!-- PREDICTION:START -->
## Current water-safety status

Assessment for **2026-09-06** — updated 2026-09-06T09:03:51Z (model v3).

| | Site | Status | Flow (live) | Why this colour |
|---|---|---|---|---|
| 🟠 | **Walton Wharf** | AMBER | 7 m³/s | Autumn/winter — only 32% safe even when dry, test first |
| 🟠 | **Chertsey** | AMBER | 9 m³/s | Autumn/winter — only 32% safe even when dry, test first |
| 🟠 | **Kingston Albany Reach** | AMBER | 4 m³/s | Autumn/winter — only 32% safe even when dry, test first |
| 🟠 | **Kingston HMT** | AMBER | 4 m³/s | Autumn/winter — only 32% safe even when dry, test first |
| 🔴 | **Ditton's Bend** | RED | 4 m³/s | Very low flow (9 m3/s) at Ditton's Bend — only 25% safe below 15 m3/s, continuous upstream effluent not diluted |
| 🔴 | **Teddington** | RED | 4 m³/s | Very low flow (9 m3/s) at Teddington — only 25% safe below 15 m3/s, continuous upstream effluent not diluted |
| 🟠 | **Hogsmill confluence** | AMBER | 4 m³/s | Autumn/winter — only 32% safe even when dry, test first |
| 🟠 | **Minima Yacht Club** | AMBER | 4 m³/s | Autumn/winter — only 32% safe even when dry, test first |

**0 🟢 GREEN · 6 🟠 AMBER · 2 🔴 RED**

_🔴 enhanced precautions · 🟠 increased precautions · 🟢 normal precautions_

_safe = EC ≤ 500 · unsafe = EC > 500 · dangerous = EC > 2000 (cfu/100ml)_

_Upstream watch (tributary flow, last 24h): Wey flat · Mole flat · Thames flat._

_Full reasoning and data quality in [`prediction.json`](prediction.json); methodology in [`EXEC-SUMMARY.md`](EXEC-SUMMARY.md)._
<!-- PREDICTION:END -->

A plain-language overview is in **[EXEC-SUMMARY.md](EXEC-SUMMARY.md)**; the complete
technical reference — inputs, decision rules, validation results, assumptions and
limitations — is in **[MODEL.md](MODEL.md)**.

## How predictions work

For a given day the model needs, per site: recent rainfall, river flow, and whether
any storm-overflow (CSO) monitors upstream have discharged. All three come from free,
public, no-authentication APIs:

| Data | Source |
|------|--------|
| River flow + rainfall | Environment Agency Hydrology API |
| Storm-overflow (CSO) discharge | Thames Water EDM API |
| E. coli test results (model calibration only) | ThamesWatch API |

The model (`tw/model.py`) is **site-specific** — each of the eight sites
has its own pollution profile. Six sites were validated against 239 real E. coli tests:
GREEN is safe **93%** of the time (and has **never** been GREEN when the water was
dangerously contaminated); RED is correct ~76% of the time. Two sites (Hogsmill confluence,
Minima Yacht Club) are newly added and pending calibration.

Eight sites, upstream → downstream (at Kingston the Thames flows south → north):

```
Chertsey ─ Wey conf. ─ Walton ─ Mole conf. ─ Minima ─║─ Hogsmill conf. ─ Albany ─ Kingston HMT ─ Teddington
                                          (control)  ║
                                       Hogsmill STW joins the Thames here
```

The Hogsmill sewage works (Berrylands) discharges into the Hogsmill, which joins the
Thames at Kingston. Its storm overflow is tracked as its own **Hogsmill** monitor and
applies only to the four sites at or below that mouth — Hogsmill confluence, Albany,
Kingston HMT and Teddington. Minima sits just *above* the mouth (the upstream control)
and is not affected by it. On 2 June 2026 Leander Sea Scouts measured EC >10,000 at the
confluence and 5,100 at Albany during an active Hogsmill discharge, while Minima — 191 m
upstream — read 530.

The biggest risk factors, in order: multiple rivers discharging sewage simultaneously,
heavy rain (>10mm/48h), rain today, and active CSO discharge. Rain raises E. coli even
with no sewage overflow — surface runoff alone washes bacteria off farmland and roads.

## Repository layout

```
README.md MODEL.md EXEC-SUMMARY.md   documentation
tw/                        core package — data gathering + the model
  config.py                central registry: APIs, stations, CSO monitors, sites
  model.py                 the prediction model (assess_safety; run: python3 -m tw.model)
  ea_hydrology.py          Environment Agency daily flow + rain fetcher
  flood_monitoring.py      EA flood-monitoring live 15-min flow (surge detection)
  thames_water.py          Thames Water CSO fetcher (status + history)
  thameswatch.py           ThamesWatch test-result fetcher
  enrichment.py            windowed rain metrics
  snapshot.py              assembles model inputs for a date, all sites
scripts/                   entry-point scripts (run from the repo root)
  predict.py               RED/AMBER/GREEN for every site (the CI entry point)
  fetch_thameswatch.py     pull raw ThamesWatch results to CSV
  fetch_upstream_cso.py    discover Thames CSO monitors upstream of Chertsey
  rebuild_correlation.py   re-enrich the calibration dataset's rain columns
  rebuild_cso.py           re-enrich the calibration dataset's CSO columns
  refresh_correlation.py   append new ThamesWatch test results to the dataset
  experiment_upstream_weighting.py   one-off near/far upstream-CSO ablation
  chart_site.py            plot test results vs the model's RAG verdict
  build_recent.py          emit recent.json (last 96h rain/flow/CSO for the web panel)
web/                       front-end snippets
  recent-panel.html        embeddable storm-panel chart (reads recent.json)
data/                      flow / rain / correlation CSVs
archive/                   superseded scripts, kept for reference
prediction.json            latest prediction (committed by the workflow)
recent.json                last 96h of rain/flow/CSO per site (committed by the workflow)
```

## Running it

```bash
pip install -r requirements.txt

python3 scripts/predict.py                       # all sites, text report
python3 scripts/predict.py --site Teddington     # one site
python3 scripts/predict.py --date 2026-05-10     # back-dated assessment
python3 scripts/predict.py --json prediction.json   # also write the JSON artifact
python3 scripts/predict.py --json -              # JSON to stdout
python3 scripts/predict.py --no-topup            # skip refreshing the flow/rain CSVs
```

A normal run refreshes the flow/rain CSVs from the EA API, fetches live CSO status,
runs the model, and prints a report:

```
ThamesWatch water safety — 2026-05-16  (model v3)
========================================================================
  AMBER  Walton Wharf              24%  2 dry day(s) — 76% safe but recent rain...
  ...
========================================================================
  0 GREEN   6 AMBER   0 RED
```

## How it runs as a workflow

`.github/workflows/predict.yml` runs **every 3 hours** (`0 */3 * * *` UTC) — frequent
enough to catch a CSO discharge or tributary surge soon after it starts, since the live
CSO current-status and 15-minute flow feeds update within ~1h. Each run:

1. Checks out the repo and installs `requests`.
2. Hard-resets to the freshest `main`, then runs `python3 scripts/predict.py --json
   prediction.json --readme README.md` — refreshing the flow/rain CSVs, fetching live CSO
   data, writing the JSON artifact, and splicing the live status block into this README.
3. Runs `python3 scripts/build_recent.py --json recent.json` — the last 96h of rain, flow
   and CSO discharge per site, for the web storm-panel chart.
4. Commits **only** the regenerated artifacts (`prediction.json`, `recent.json`,
   `README.md`, `data/` CSVs) and pushes, regenerating against latest `main` on each retry
   so a concurrent merge is never reverted.

### Embedding the data on a website

Both JSON files have stable `raw.githubusercontent.com` URLs and `access-control-allow-origin: *`,
so a browser can fetch them directly. `prediction.json` is the current RED/AMBER/GREEN per
site; `recent.json` is the 96h time-series behind it. `web/recent-panel.html` is a
drop-in, no-build Chart.js panel (rainfall bars → sewage-overflow bands → river-flow line)
that reads `recent.json` — paste it into a WordPress Custom HTML block.

No secrets or API keys are needed — every data source is public. The workflow can
also be triggered manually from the Actions tab (`workflow_dispatch`).

## The output — `prediction.json`

Each run commits `prediction.json` (versioned via `schema_version`). Its stable
`raw.githubusercontent.com` URL is intended to feed a website.

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-16T09:03:13Z",
  "assessment_date": "2026-05-16",
  "model_version": "v3",
  "sites": [
    {
      "site": "Walton Wharf",
      "level": "AMBER",
      "confidence": 24,
      "explanation": "2 dry day(s) — 76% safe but recent rain, consider testing",
      "why_detail": "Wey: Woking 7.2h, Ripley 2.8h · ThamesUpstream: Windsor 7.1h · Wey flow rising (7.3 m³/s)",
      "live_flow_m3s": 25.1, "flow_gauge": "walton",
      "inputs": {
        "rain_48h": 0.0, "rain_7d": 6.05, "dry_days": 2, "season": "spring",
        "flow_m3s": 28.373, "cso_active_48h": false, "cso_hours_48h": 0.0,
        "cso_active_monitors": "", "upstream_ctx": { ... }
      },
      "data_quality": {
        "rain_station": "hogsmill_rain", "flow_data_date": "2026-05-14",
        "data_lag_days": 2, "warnings": ["flow data 2 day(s) behind assessment date"]
      }
    }
  ],
  "summary": { "GREEN": 0, "AMBER": 6, "RED": 0 }
}
```

- **`level` / `confidence` / `explanation`** — the verdict and why.
- **`why_detail`** — the specifics behind the verdict: the site-relevant active CSOs with
  discharge hours, notable rain, and any tributary surge (also shown in the README status
  table's "Why" column).
- **`live_flow_m3s` / `flow_gauge`** — the current Thames flow at the site's nearest live
  gauge (Staines / Walton / Kingston), shown in the status table's "Flow" column. Safety
  context — high flow means strong currents irrespective of water quality. Display-only;
  the model's flow *thresholds* still use the Walton daily mean (`inputs.flow_m3s`).
- **`inputs`** — the exact values fed to the model, so a consumer can show the reasoning.
- **`data_quality`** — provenance and staleness. EA daily data lags 1-3 days; when the
  assessment date's flow isn't published yet the most recent reading is used and a
  warning records the lag.

The JSON also carries an **`upstream_watch`** block — a catchment-level early-warning
view (separate from the per-site verdicts): recent rainfall in the Wey, Mole, and Thames
headwaters, and each tributary's flow trend over the last 24h (surge / rising / flat /
easing). On a live run the flow trend comes from the 15-minute series — the same data
the model's live surge detection uses, so the panel and the model agree. Headwater rain
reaches the stretch ~1-3 days later, so a rising tributary flags conditions arriving
before they show up locally.

## Maintaining the model

The model is calibrated against `data/thameswatch_correlation_with_cso.csv` — real
E. coli tests paired with rain/flow/CSO conditions.

- `scripts/fetch_thameswatch.py` pulls the latest raw test results.
- `scripts/refresh_correlation.py` appends any new results to the calibration dataset.
- `scripts/rebuild_correlation.py` re-computes the dataset's rain enrichment.
- `scripts/rebuild_cso.py` re-computes the dataset's CSO enrichment against the current monitor set.
- `python3 -m tw.model --validate` reports model accuracy.

Re-validate after adding data: the hard gate is **0% dangerous-in-GREEN**; GREEN-safe sits ~93% (the shortfall is the irreducible spring spikes — see MODEL.md §9).

### Upstream-of-Chertsey Thames CSOs

The CSO network historically began at Chertsey (the top of the stretch), so Chertsey had
no upstream storm-overflow predictor — its relevance was the Wey, which actually joins
downstream at Weybridge and so cannot reach it. The Thames-mainstem overflows *above*
Chertsey are its only valid CSO predictor, and Chertsey's relevance is now
`ThamesUpstream` alone (the Wey was dropped).

These monitors are hard-coded in `tw/config.py` as `ThamesUpstream` `CSOMonitor` records —
the same discover-once-then-freeze pattern as the in-stretch monitors and the EA station
GUIDs. `scripts/fetch_upstream_cso.py` is the discovery tool, not a runtime dependency:

```bash
python3 scripts/fetch_upstream_cso.py                   # discover -> print paste-ready records + data/ provenance CSV
# paste the NEAR records into tw/config.py CSO_MONITORS, then:
python3 scripts/rebuild_cso.py                           # re-enrich all historical CSO columns with the new set
python3 -m tw.model --validate     # review the impact
```

**Only the two monitors closest to Chertsey are kept** (Windsor ~5 km, Little Marlow
~17 km). An ablation (`scripts/experiment_upstream_weighting.py`) showed the three farther ones
(Reading, Henley, Hambleden — 26–32 km up, beyond ~1–2 days of *E. coli* die-off and
dilution) caught zero extra unsafe-in-GREEN days while removing 7 safe days from GREEN —
pure false-conservatism. `ThamesUpstream` is a distinct river system, so the multi-river
RED rule can trip on Wey + ThamesUpstream at Walton; the GREEN-availability trade-off is
favourable (GREEN stays ~93% safe, 0% dangerous).
