# ThamesWatch — water-safety prediction

A traffic-light model that predicts whether the River Thames is safe for water
activities at the Walton Viking Sea Scouts' stretch — **before** you get to the water,
without waiting 24-48h for a lab result.

It checks rainfall, river flow, and sewage-discharge conditions and returns a
**RED / AMBER / GREEN** verdict for each test site:

- 🔴 **RED** — do not go on the water. Unsafe ~80% of the time in these conditions.
- 🟠 **AMBER** — borderline. Test the water with an R-Card first; if you can't test, don't go.
- 🟢 **GREEN** — go with confidence. Safe ~95% of the time.

<!-- PREDICTION:START -->
## Current water-safety status

Assessment for **2026-05-18** — updated 2026-05-18T13:27:40Z (model v3).

| | Site | Status | Why this colour |
|---|---|---|---|
| 🟢 | **Walton Wharf** | GREEN | Dry conditions (4d), no CSO, spring — safe |
| 🟢 | **Chertsey** | GREEN | Dry conditions (4d), no CSO, spring — safe |
| 🟠 | **Kingston Albany Reach** | AMBER | Kingston Albany Reach has elevated baseline from continuous upstream effluent — test first |
| 🟢 | **Kingston HMT** | GREEN | Dry conditions (4d), no CSO, spring — safe |
| 🟠 | **Ditton's Bend** | AMBER | Ditton's Bend has elevated baseline from continuous upstream effluent — test first |
| 🟠 | **Teddington** | AMBER | Teddington has elevated baseline from continuous upstream effluent — test first |

**3 🟢 GREEN · 3 🟠 AMBER · 0 🔴 RED**

_🔴 do not go on the water · 🟠 test the water with an R-Card first · 🟢 good to go_

_Upstream watch (tributary flow, last 24h): Wey flat · Mole flat · Thames rising._

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

The model (`traffic_light_model_v3.py`) is **site-specific** — each of the six sites
has its own pollution profile. It was validated against 229 real E. coli tests:
GREEN is safe **95%** of the time (and has **never** been GREEN when the water was
dangerously contaminated); RED is correct ~80% of the time.

Six sites, upstream → downstream:

```
Chertsey ─ Walton Wharf ─ Wey confluence ─ Mole confluence ─ Kingston ─ Teddington
```

The biggest risk factors, in order: multiple rivers discharging sewage simultaneously,
heavy rain (>10mm/48h), rain today, and active CSO discharge. Rain raises E. coli even
with no sewage overflow — surface runoff alone washes bacteria off farmland and roads.

## Repository layout

```
predict.py                 entry point — RED/AMBER/GREEN for every site
traffic_light_model_v3.py  the prediction model (assess_safety)
tw/                        data-gathering package
  config.py                central registry: APIs, stations, CSO monitors, sites
  ea_hydrology.py           Environment Agency flow + rain fetcher
  thames_water.py           Thames Water CSO fetcher (status + history)
  thameswatch.py            ThamesWatch test-result fetcher
  enrichment.py             windowed rain metrics
  snapshot.py               assembles model inputs for a date, all sites
rebuild_correlation.py     re-enrich the calibration dataset's rain columns
refresh_correlation.py     append new ThamesWatch test results to the dataset
fetch_thameswatch.py       pull raw ThamesWatch results to CSV
data/                      flow / rain / correlation CSVs
archive/                   superseded scripts, kept for reference
prediction.json            latest prediction (committed by the workflow)
```

## Running it

```bash
pip install -r requirements.txt

python3 predict.py                       # all sites, text report
python3 predict.py --site Teddington     # one site
python3 predict.py --date 2026-05-10     # back-dated assessment
python3 predict.py --json prediction.json   # also write the JSON artifact
python3 predict.py --json -              # JSON to stdout
python3 predict.py --no-topup            # skip refreshing the flow/rain CSVs
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

`.github/workflows/predict.yml` runs **twice daily** — 06:00 and 12:00 UTC (morning
and early afternoon UK time, so an afternoon check catches rain or CSO that landed
during the day). Each run:

1. Checks out the repo and installs `requests`.
2. Runs `python3 predict.py --json prediction.json --readme README.md` — refreshing the
   flow/rain CSVs, fetching live CSO data, writing the JSON artifact, and splicing the
   live status block into this README.
3. Commits the updated `prediction.json`, `README.md` and `data/` CSVs back to the repo.

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

- `fetch_thameswatch.py` pulls the latest raw test results.
- `refresh_correlation.py` appends any new results to the calibration dataset.
- `rebuild_correlation.py` re-computes the dataset's rain enrichment.
- `python3 traffic_light_model_v3.py --validate` reports model accuracy.

Re-validate after adding data: GREEN should stay ~95% safe with 0% dangerous.
