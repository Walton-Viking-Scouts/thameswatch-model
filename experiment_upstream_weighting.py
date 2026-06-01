#!/usr/bin/env python3
"""One-off ablation: do the FAR upstream-of-Chertsey Thames CSO monitors add
predictive value, or only the near ones (Windsor + Little Marlow)?

Compares three monitor sets against the historical record, varying ONLY which
upstream-of-Chertsey Thames monitors the model can see (the existing 14 in-stretch
monitors are constant). Classification is run in-memory — no CSV is mutated — so the
committed dataset is untouched. Chertsey relevance is fixed to ThamesUpstream-only
throughout (the geography fix) so only the monitor set varies.

    none   — no upstream monitors (pre-feature behaviour)
    near2  — Windsor + Little Marlow only (the two closest to Chertsey)
    all5   — Reading, Henley, Hambleden, Little Marlow, Windsor

Run where outbound network is available (fetches discharge history once, caches to /tmp).
"""

import csv
import json
import os
from datetime import datetime

import tw.config as config
import traffic_light_model_v3 as model
from tw.config import CSOMonitor
from tw.paths import data_file
from tw.thames_water import (
    build_discharge_periods, count_cso_hours, fetch_monitor_history, was_cso_active,
)

# The in-stretch monitors, held constant across variants.
EXISTING_RECORDS = [m for m in config.CSO_MONITORS if m.river_system != "ThamesUpstream"]
EXISTING = [m.name for m in EXISTING_RECORDS]

# All five discovered upstream-of-Chertsey monitors, with their EDM coordinates.
UPSTREAM_RECORDS = [
    CSOMonitor("Reading, Caversham", "ThamesUpstream", 472800, 174500),
    CSOMonitor("Friday Street, Henley", "ThamesUpstream", 476300, 182700),
    CSOMonitor("Hambleden", "ThamesUpstream", 478600, 184800),
    CSOMonitor("Little Marlow", "ThamesUpstream", 487710, 186960),
    CSOMonitor("Windsor", "ThamesUpstream", 499700, 175000),
]
UPSTREAM_ALL = [m.name for m in UPSTREAM_RECORDS]
NEAR2 = ["Little Marlow", "Windsor"]

VARIANTS = {"none": [], "near2": NEAR2, "all5": UPSTREAM_ALL}

CACHE = "/tmp/upstream_experiment_periods.json"


def load_periods():
    """{name: [(start,stop), ...]} for existing 14 + all 5 upstream, cached to /tmp."""
    names = EXISTING + UPSTREAM_ALL
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE))
        return {n: [(datetime.fromisoformat(a), datetime.fromisoformat(b))
                    for a, b in raw.get(n, [])] for n in names}
    print(f"Fetching discharge history for {len(names)} monitors (one-time, cached)...")
    periods = {n: build_discharge_periods(fetch_monitor_history(n)) for n in names}
    json.dump({n: [(a.isoformat(), b.isoformat()) for a, b in p]
               for n, p in periods.items()}, open(CACHE, "w"))
    return periods


def classify_variant(rows, all_periods, upstream_subset):
    """Return per-bucket safety tallies for one monitor set, plus GREEN-but-unsafe rows."""
    active_names = EXISTING + upstream_subset
    periods = {n: all_periods[n] for n in active_names}
    # Point the model's single source of truth (config.CSO_MONITORS, read by
    # count_active_river_systems) at exactly this variant's monitor set.
    config.CSO_MONITORS = EXISTING_RECORDS + [
        m for m in UPSTREAM_RECORDS if m.name in upstream_subset]

    buckets = {lvl: {"n": 0, "safe": 0, "unsafe": 0, "danger": 0}
               for lvl in ("GREEN", "AMBER", "RED")}
    green_unsafe = []
    for row in rows:
        test_dt = datetime.strptime(row["date"], "%Y-%m-%d").replace(hour=12)
        active_48, _ = was_cso_active(periods, test_dt, 48)
        hours_48, monitors_48 = count_cso_hours(periods, test_dt, 48)
        monitors_str = "; ".join(f"{nm}({h}h)" for nm, h in monitors_48)

        flow = model.get_walton_flow().get(row["date"])
        ctx = model.get_upstream_context(row["date"])
        rain_7d = float(row["rain_7d"]) if row.get("rain_7d") else None
        level, _, _ = model.assess_safety(
            float(row["rain_48h"]), float(row["dry_days"]), row["season"],
            active_48, hours_48, monitors_str, row["site"], flow, rain_7d, ctx)

        ec = float(row["ec"])
        b = buckets[level]
        b["n"] += 1
        b["safe"] += ec <= 500
        b["unsafe"] += ec > 500
        b["danger"] += ec > 2000
        if level == "GREEN" and ec > 500:
            green_unsafe.append((row["site"], row["date"], int(ec), monitors_str))
    return buckets, green_unsafe


def main():
    rows = list(csv.DictReader(open(data_file("thameswatch_correlation_with_cso.csv"))))
    all_periods = load_periods()
    # Geography fix #1, held constant across variants so only the monitor set moves.
    model.SITE_CSO_RELEVANCE["Chertsey"] = ["ThamesUpstream"]

    print(f"\n{len(rows)} historical samples · existing monitors held constant · "
          "Chertsey=ThamesUpstream-only\n")
    print(f"{'variant':<7} {'GREEN n':>7} {'safe%':>6} {'unsafe%':>8} {'danger%':>8}  "
          f"{'GREEN-unsafe':>12}")
    results = {}
    for name, subset in VARIANTS.items():
        buckets, gu = classify_variant(rows, all_periods, subset)
        results[name] = (buckets, gu)
        g = buckets["GREEN"]
        sp = g["safe"] / g["n"] * 100 if g["n"] else 0
        up = g["unsafe"] / g["n"] * 100 if g["n"] else 0
        dp = g["danger"] / g["n"] * 100 if g["n"] else 0
        print(f"{name:<7} {g['n']:>7} {sp:>5.0f}% {up:>7.0f}% {dp:>7.0f}%  {len(gu):>9} days")

    # What does each upstream set newly catch, vs leave missed, in GREEN?
    base_gu = {(s, d) for s, d, _, _ in results["none"][1]}
    for name in ("near2", "all5"):
        gu = results[name][1]
        caught = base_gu - {(s, d) for s, d, _, _ in gu}
        print(f"\n{name}: GREEN-but-unsafe days newly caught vs 'none': {len(caught)}")
        still = [x for x in gu]
        print(f"  still GREEN-but-unsafe under {name}: {len(still)}")
        for s, d, ec, mon in sorted(still, key=lambda x: -x[2]):
            print(f"    {d}  {s:22s} EC={ec:5d}  {mon[:60]}")


if __name__ == "__main__":
    main()
