#!/usr/bin/env python3
"""Discover Thames Water storm-overflow (CSO) monitors on the Thames mainstem UPSTREAM
of Chertsey — the developer tool used to source the ThamesUpstream monitors in tw.config.

This is a *discovery* tool, not a runtime data source. Like archive/fetch_cso_outfalls.py
(which sourced the in-stretch CSO_MONITORS) and ea_hydrology.search_stations (which sourced
the EA station GUIDs), it queries the live EDM feed, prints paste-ready CSOMonitor records,
and writes a provenance CSV to data/. The monitor list itself is then hard-coded into
tw.config.CSO_MONITORS — config is developer-edited, so the model never depends on whether
a file happens to be present on disk.

The model's CSO network historically began at Chertsey (the top of the monitored stretch),
so Chertsey had no upstream-CSO predictor — its relevance was the Wey, which actually joins
downstream at Weybridge. This finds the Thames-mainstem overflows above Chertsey.

Distance matters: an ablation (experiment_upstream_weighting.py) found only the two CLOSEST
monitors (Windsor ~5 km, Little Marlow ~17 km) carry signal; the farther three (Reading,
Henley, Hambleden — 26-32 km up, beyond ~1-2 days of E. coli die-off) added only
false-conservatism. The "near/far" column below records that cut; keep only NEAR monitors.

    python3 fetch_upstream_cso.py                   # discover -> print records + data/ CSV
    # paste the NEAR records into tw.config.CSO_MONITORS, then:
    python3 rebuild_cso.py                          # re-enrich history with the new set
    python3 traffic_light_model_v3.py --validate    # review the impact

Run where outbound network is available (CI or locally — not the restricted sandbox).
"""

import csv
import os

from tw.paths import DATA_DIR
from tw.thames_water import fetch_current_status

# Chertsey test site sits at OS easting ~505,000. The Thames runs broadly W->E through
# Reading -> Staines -> Chertsey, so "upstream of Chertsey" means a lower easting. Bound
# the search to the Thames reach from roughly Reading down to Chertsey.
CHERTSEY_EASTING = 505000
MIN_EASTING = 465000
MIN_NORTHING, MAX_NORTHING = 158000, 192000

# Easting distance from Chertsey beyond which a monitor adds only false-conservatism
# (see the ablation referenced above). ~20 km straddles Little Marlow (kept) / Hambleden.
NEAR_KM = 20.0

OUT_CSV = os.path.join(DATA_DIR, "cso_upstream_chertsey.csv")
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


def km_from_chertsey(m):
    """Rough straight-line km upstream (easting delta only — the reach runs ~W->E)."""
    return (CHERTSEY_EASTING - (m.get("x") or 0)) / 1000.0


def main():
    print("Fetching all Thames Water EDM monitor statuses...")
    items = fetch_current_status()
    print(f"  {len(items)} monitors total")
    if not items:
        raise SystemExit(
            "EDM /discharge/status returned no monitors — almost certainly an API error "
            "(auth / rate-limit / outage), not an empty feed. Refusing to overwrite "
            f"{OUT_CSV} with empty data; check the network and re-run.")

    upstream = sorted((m for m in items if is_upstream_thames(m)),
                      key=lambda m: m.get("x") or 0)
    print(f"  {len(upstream)} on the Thames upstream of Chertsey "
          f"(easting {MIN_EASTING}-{CHERTSEY_EASTING})\n")

    print(f"  {'~km up':>6}  {'near/far':<8} {'status':<18} name")
    for m in upstream:
        dist = km_from_chertsey(m)
        tier = "NEAR" if dist <= NEAR_KM else "far"
        print(f"  {dist:>6.1f}  {tier:<8} {(m.get('alertStatus') or ''):<18} "
              f"{m.get('locationName', '')}")

    print("\n  Paste-ready records for tw.config.CSO_MONITORS (NEAR only):")
    for m in upstream:
        if km_from_chertsey(m) <= NEAR_KM:
            print(f'    CSOMonitor("{m.get("locationName","")}", "ThamesUpstream", '
                  f'{m.get("x")}, {m.get("y")}),')

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for m in upstream:
            w.writerow({k: m.get(k, "") for k in FIELDS})
    print(f"\nWrote provenance for {len(upstream)} discovered monitors -> {OUT_CSV}")
    print("Next: paste NEAR records into tw/config.py, then python3 rebuild_cso.py")


if __name__ == "__main__":
    main()
