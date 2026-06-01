#!/usr/bin/env python3
"""Refresh the correlation dataset with new ThamesWatch results — append-only.

The model validates against thameswatch_correlation_with_cso.csv. Rather than rebuild
all 207 rows (whose original /tmp rain inputs are gone — re-deriving risks conflating
'new data' with 'changed enrichment'), this keeps the verified rows verbatim and appends
only test results not already present, enriched with the same rain + CSO logic.

Inputs:
  - thameswatch_results.csv          (from fetch_thameswatch.py)
  - thameswatch_correlation_with_cso.csv  (existing verified dataset)
  - EA Hydrology  — Hogsmill daily rain gauge (primary_rain, same as original build)
  - Thames Water  — CSO discharge alert history (via fetch_cso_history.py logic)

Output: thameswatch_correlation_with_cso.csv (rewritten = old rows + new rows)

Usage:
    python3 refresh_correlation.py
"""

import csv
from datetime import datetime

from tw.config import CSO_MONITOR_NAMES, SITE_BY_THAMESWATCH_LOCATION as SITE_MAP
from tw.ea_hydrology import fetch_station_readings
from tw.enrichment import calc_rain_metrics, season_of
from tw.paths import data_file
from tw.thames_water import (
    build_discharge_periods, count_cso_hours, fetch_monitor_history, was_cso_active,
)

RESULTS_CSV = data_file("thameswatch_results.csv")
CORR_CSV = data_file("thameswatch_correlation_with_cso.csv")

CORR_FIELDS = ["site", "date", "ec", "ei", "season", "rain_24h", "rain_48h", "rain_72h",
               "rain_7d", "dry_days", "max_rain_3d", "teddington_level", "cso_active_48h",
               "cso_hours_48h", "cso_active_monitors", "cso_active_72h", "cso_hours_72h"]


def main():
    # Existing verified dataset — kept verbatim
    with open(CORR_CSV) as f:
        existing = list(csv.DictReader(f))
    seen = {(r["site"], r["date"]) for r in existing}
    print(f"Existing dataset: {len(existing)} rows")

    # New ThamesWatch results for the 6 model sites, not already present
    with open(RESULTS_CSV) as f:
        new_results = []
        for r in csv.DictReader(f):
            site = SITE_MAP.get(r["locationName"])
            if not site or not r["testDate"] or r["ec"] in (None, ""):
                continue
            if (site, r["testDate"]) in seen:
                continue
            new_results.append({"site": site, "date": r["testDate"],
                                 "ec": r["ec"], "ei": r["ei"]})
    new_results.sort(key=lambda r: (r["site"], r["date"]))
    print(f"New results to enrich: {len(new_results)}")
    if not new_results:
        print("Nothing new — dataset already current.")
        return

    # Enrichment data — Hogsmill rain (all sites use it; see config.SITES comment)
    print("Fetching Hogsmill rain...")
    rain = fetch_station_readings("hogsmill_rain")
    print(f"  {len(rain)} days ({min(rain)} to {max(rain)})")

    print(f"Fetching CSO discharge history ({len(CSO_MONITOR_NAMES)} monitors)...")
    periods = {}
    for name in CSO_MONITOR_NAMES:
        periods[name] = build_discharge_periods(fetch_monitor_history(name))
    print(f"  {sum(len(p) for p in periods.values())} discharge events total")

    # Enrich
    enriched = []
    for n in new_results:
        m = calc_rain_metrics(rain, n["date"])
        test_dt = datetime.strptime(n["date"], "%Y-%m-%d").replace(hour=12)
        active_48, _ = was_cso_active(periods, test_dt, 48)
        hours_48, monitors_48 = count_cso_hours(periods, test_dt, 48)
        active_72, _ = was_cso_active(periods, test_dt, 72)
        hours_72, _ = count_cso_hours(periods, test_dt, 72)
        enriched.append({
            "site": n["site"], "date": n["date"], "ec": n["ec"], "ei": n["ei"] or "",
            "season": season_of(n["date"]),
            "rain_24h": m["rain_24h"], "rain_48h": m["rain_48h"],
            "rain_72h": m["rain_72h"], "rain_7d": m["rain_7d"],
            "dry_days": m["dry_days"], "max_rain_3d": m["max_rain_3d"],
            "teddington_level": "",
            "cso_active_48h": str(active_48), "cso_hours_48h": str(hours_48),
            "cso_active_monitors": "; ".join(f"{nm}({h}h)" for nm, h in monitors_48),
            "cso_active_72h": str(active_72), "cso_hours_72h": str(hours_72),
        })

    # Write old + new
    with open(CORR_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CORR_FIELDS)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerows(enriched)

    print(f"\nWrote {len(existing) + len(enriched)} rows -> {CORR_CSV}")
    print(f"  ({len(existing)} kept verbatim + {len(enriched)} appended)")
    print("\nNew rows:")
    for e in enriched:
        cso = "CSO" if e["cso_active_48h"] == "True" else "   "
        print(f"  {e['site']:24s} {e['date']}  EC={e['ec']:>5}  "
              f"rain48={e['rain_48h']:>5}  dry={e['dry_days']:>2}  {cso}")


if __name__ == "__main__":
    main()
