#!/usr/bin/env python3
"""Rebuild the CSO enrichment of the correlation dataset from the current monitor set.

Counterpart to rebuild_correlation.py (which rebuilds the rain_* columns). This re-computes
the cso_* columns of *every* row in thameswatch_correlation_with_cso.csv against the full
current monitor set (config.CSO_MONITOR_NAMES) — including any upstream-of-Chertsey Thames
monitors discovered by fetch_upstream_cso.py.

This is what lets a validation run "see" the new monitors in the historical record:
refresh_correlation.py only enriches newly-appended rows and keeps existing rows verbatim,
so without this step the 229 historical tests would never reflect the upstream CSOs.

Only the cso_* columns change; ec/ei/season and the rain_* columns are left untouched. A
timestamped backup of the dataset is written to /tmp before the rewrite.

Run where outbound network is available (it fetches each monitor's discharge history):

    python3 rebuild_cso.py
    python3 traffic_light_model_v3.py --validate
"""

import csv
import shutil
from datetime import datetime, timezone

from tw.config import CSO_MONITOR_NAMES, UPSTREAM_THAMES_NAMES
from tw.paths import data_file
from tw.thames_water import (
    build_discharge_periods, count_cso_hours, fetch_monitor_history, was_cso_active,
)

CSO_COLS = ("cso_active_48h", "cso_hours_48h", "cso_active_monitors",
            "cso_active_72h", "cso_hours_72h")


def main():
    corr_path = data_file("thameswatch_correlation_with_cso.csv")
    with open(corr_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames

    backup = (f"/tmp/correlation_pre_cso_rebuild_"
              f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv")
    shutil.copy(corr_path, backup)

    n_up = len(UPSTREAM_THAMES_NAMES)
    print(f"CSO monitor set: {len(CSO_MONITOR_NAMES)} total "
          f"({n_up} upstream-of-Chertsey){' — run fetch_upstream_cso.py first' if n_up == 0 else ''}")
    print("Fetching CSO discharge history...")
    periods = {name: build_discharge_periods(fetch_monitor_history(name))
               for name in CSO_MONITOR_NAMES}
    print(f"  {sum(len(p) for p in periods.values())} discharge events total")

    changed = 0
    for row in rows:
        test_dt = datetime.strptime(row["date"], "%Y-%m-%d").replace(hour=12)
        active_48, _ = was_cso_active(periods, test_dt, 48)
        hours_48, monitors_48 = count_cso_hours(periods, test_dt, 48)
        active_72, _ = was_cso_active(periods, test_dt, 72)
        hours_72, _ = count_cso_hours(periods, test_dt, 72)
        new = {
            "cso_active_48h": str(active_48),
            "cso_hours_48h": str(hours_48),
            "cso_active_monitors": "; ".join(f"{nm}({h}h)" for nm, h in monitors_48),
            "cso_active_72h": str(active_72),
            "cso_hours_72h": str(hours_72),
        }
        if any(str(row.get(c)) != new[c] for c in CSO_COLS):
            changed += 1
        row.update(new)

    with open(corr_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"\nRebuilt CSO enrichment for {len(rows)} rows ({changed} changed).")
    print(f"Backup of the pre-rebuild dataset: {backup}")
    print("Next: python3 traffic_light_model_v3.py --validate")


if __name__ == "__main__":
    main()
