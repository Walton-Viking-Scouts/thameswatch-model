#!/usr/bin/env python3
"""Rebuild the rain enrichment of the correlation dataset from configured gauges.

Re-computes the rain_* columns of every row in thameswatch_correlation_with_cso.csv
using each row's site's configured rain gauge (config.SITES[...].rain_station_key) and
the current rain CSVs. This keeps the calibration dataset consistent with whatever
gauge the live prediction path uses.

All sites currently use the Hogsmill gauge — a per-catchment mapping was tested and
re-validated on 2026-05-16 and slightly underperformed (see config.SITES comment).

EC, EI, season, teddington_level and the cso_* columns are left untouched — only the
rain columns change. Run `traffic_light_model_v3.py --validate` afterwards to confirm
model accuracy still holds.

Usage:
    python3 rebuild_correlation.py
"""

import csv
import shutil
import sys
from datetime import datetime, timezone

from tw import config
from tw.enrichment import calc_rain_metrics
from tw.paths import data_file

RAIN_COLS = ("rain_24h", "rain_48h", "rain_72h", "rain_7d", "dry_days", "max_rain_3d")


def load_rain_csv(path):
    """Load a date,value rain CSV into {date_str: mm}."""
    rain = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("date"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    rain[parts[0]] = float(parts[1])
                except ValueError:
                    pass
    return rain


def main():
    corr_path = data_file("thameswatch_correlation_with_cso.csv")

    with open(corr_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames

    backup = f"/tmp/correlation_pre_percatchment_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    shutil.copy(corr_path, backup)

    # Load each per-catchment rain gauge once.
    rain_by_gauge = {}
    for key in sorted({s.rain_station_key for s in config.SITES.values()}):
        rain_by_gauge[key] = load_rain_csv(data_file(config.RAIN_CSV[key]))
        print(f"  {key}: {len(rain_by_gauge[key])} days loaded")

    changed = 0
    for row in rows:
        site = config.SITES.get(row["site"])
        if not site:
            print(f"  WARNING: unknown site '{row['site']}' — left unchanged", file=sys.stderr)
            continue
        gauge = rain_by_gauge[site.rain_station_key]
        old_48h = row.get("rain_48h")
        metrics = calc_rain_metrics(gauge, row["date"])
        for col in RAIN_COLS:
            row[col] = metrics[col]
        if str(old_48h) != str(metrics["rain_48h"]):
            changed += 1

    with open(corr_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nRebuilt per-catchment rain enrichment for {len(rows)} rows "
          f"({changed} rain_48h values changed).")
    print(f"Backup of the pre-rebuild dataset: {backup}")
    print("Next: python3 traffic_light_model_v3.py --validate")


if __name__ == "__main__":
    main()
