#!/usr/bin/env python3
"""Discover Thames Water storm-overflow (CSO) monitors on the Thames mainstem UPSTREAM
of Chertsey, and cache them for the model.

The model's CSO network historically began at Chertsey — the top of the monitored
stretch — so Chertsey's own contamination had no upstream-CSO predictor (its hard-coded
relevance was the Wey, which actually joins the Thames *downstream* at Weybridge). This
script queries the EDM /discharge/status feed, selects monitors discharging into the
River Thames west (upstream) of Chertsey, and writes data/cso_upstream_chertsey.csv.
tw.config loads that file at import, tagging each monitor as a "ThamesUpstream" system
relevant to every site.

Run where outbound network is available (CI or locally — not the restricted sandbox):

    python3 fetch_upstream_cso.py
    python3 rebuild_cso.py                          # re-enrich history with the new monitors
    python3 traffic_light_model_v3.py --validate    # review the impact
"""

import csv

from tw.paths import data_file
from tw.thames_water import fetch_current_status

# Chertsey test site sits at OS easting ~504,700. The Thames runs broadly W->E through
# Reading -> Staines -> Chertsey, so "upstream of Chertsey" means a lower easting. Bound
# the search to the Thames reach from roughly Reading down to Chertsey.
CHERTSEY_EASTING = 505000
MIN_EASTING = 465000
MIN_NORTHING, MAX_NORTHING = 158000, 192000

OUT_CSV = data_file("cso_upstream_chertsey.csv")
FIELDS = ["locationName", "permitNumber", "receivingWaterCourse", "x", "y",
          "alertStatus", "statusChanged", "mostRecentDischargeAlertStart",
          "mostRecentDischargeAlertStop", "alertPast48Hours"]


def is_upstream_thames(m):
    """True if a status record is a Thames-mainstem monitor upstream of Chertsey."""
    wc = (m.get("receivingWaterCourse") or "").lower()
    x = m.get("x") or 0
    y = m.get("y") or 0
    return ("thames" in wc
            and MIN_EASTING <= x < CHERTSEY_EASTING
            and MIN_NORTHING <= y <= MAX_NORTHING)


def main():
    print("Fetching all Thames Water EDM monitor statuses...")
    items = fetch_current_status()
    print(f"  {len(items)} monitors total")

    upstream = sorted((m for m in items if is_upstream_thames(m)),
                      key=lambda m: m.get("x") or 0)
    print(f"  {len(upstream)} on the Thames upstream of Chertsey "
          f"(easting {MIN_EASTING}-{CHERTSEY_EASTING})\n")
    print(f"  {'easting':>7} {'northing':>8}  {'status':<18} name")
    for m in upstream:
        print(f"  {m.get('x', ''):>7} {m.get('y', ''):>8}  "
              f"{(m.get('alertStatus') or ''):<18} {m.get('locationName', '')}")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for m in upstream:
            w.writerow({k: m.get(k, "") for k in FIELDS})
    print(f"\nWrote {len(upstream)} monitors -> {OUT_CSV}")
    print("Next: python3 rebuild_cso.py && python3 traffic_light_model_v3.py --validate")


if __name__ == "__main__":
    main()
