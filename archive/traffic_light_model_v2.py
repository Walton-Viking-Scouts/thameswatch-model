#!/usr/bin/env python3
"""
ThamesWatch Traffic Light Model v2.1 — with CSO layer + multi-river detection

Predicts water safety for scout activities based on:
  1. Recent rainfall (48h)
  2. Dry days since last significant rain
  3. Season
  4. CSO discharge activity (48h) — NEW in v2
  5. Multi-river CSO detection (Wey + Mole simultaneous) — NEW in v2.1

Usage:
    python3 traffic_light_model_v2.py                    # Interactive mode
    python3 traffic_light_model_v2.py --validate         # Validate against historical data
"""

import csv
import sys
from collections import defaultdict


# === MODEL DEFINITION ===

def count_active_river_systems(cso_active_monitors_str):
    """
    Classify active CSO monitors into river systems and count how many are active.

    Returns (systems_active, system_names) where systems_active is the count
    of distinct river systems with active CSOs.

    River systems:
    - Wey: Ripley, Weybridge, Woking — joins Thames above Walton
    - Mole: Esher, Cobham, Stoke Road, Leatherhead, River Lane — joins at East Molesey
    - Thames direct: Kingston Main, Portsmouth Road, Amyand Park Road, Old Palace Lane
    - Minor: Commonside (Bookham Brook), Dartnell Park (Rive Ditch)
    """
    if not cso_active_monitors_str:
        return 0, []

    systems = set()
    if any(name in cso_active_monitors_str for name in ["Ripley", "Weybridge", "Woking"]):
        systems.add("Wey")
    if any(name in cso_active_monitors_str for name in ["Esher", "Cobham", "Stoke Road", "Leatherhead", "River Lane"]):
        systems.add("Mole")
    if any(name in cso_active_monitors_str for name in ["Kingston", "Portsmouth", "Amyand", "Old Palace"]):
        systems.add("Thames")
    if any(name in cso_active_monitors_str for name in ["Commonside", "Dartnell"]):
        systems.add("Minor")

    return len(systems), sorted(systems)


def assess_safety(rain_48h, dry_days, season, cso_active_48h, cso_hours_48h=0,
                  cso_active_monitors_str=""):
    """
    Returns (level, confidence, explanation) where level is GREEN/AMBER/RED.

    v2.1 model trained on 207 samples with CSO correlation data from 14 upstream monitors.

    Key findings from cross-tabulation:
    - CSO active + moderate rain: only 16% safe (vs 55% without CSO)
    - CSO active + 0 dry days: only 11% safe (vs 35% without)
    - CSO active in spring: drops from 92% safe to 41%
    - >50h CSO discharge: only 5% safe
    - Both Wey + Mole active: 0% safe, 59% dangerous (n=34) — NEW in v2.1
    - Single river CSO: 33-46% safe — bad but not as catastrophic
    """
    is_summer_spring = season in ("spring", "summer")
    multi_river_count, river_names = count_active_river_systems(cso_active_monitors_str)
    multi_river = multi_river_count >= 2

    # RED conditions — don't go

    # Multi-river CSO: 0% safe, 59% dangerous (n=34) — worst scenario in dataset
    if multi_river:
        rivers = " + ".join(river_names)
        return "RED", 100, f"Multiple river CSOs active ({rivers}) — 0% safe in 34 historical cases"

    # Heavy rain (>10mm/48h): 5-20% safe regardless of CSO
    if rain_48h > 10:
        return "RED", 95, f"Heavy rain ({rain_48h:.0f}mm/48h) — only 5-20% chance of safe levels"

    # Rained today + CSO active: 11% safe
    if dry_days == 0 and cso_active_48h:
        return "RED", 89, f"Rain today + CSO discharging — only 11% safe historically"

    # Rained today without CSO: 35% safe — still risky
    if dry_days == 0:
        return "RED", 65, f"Rained today — only 35% safe even without CSO"

    # Moderate rain + CSO active: 16% safe
    if rain_48h > 2 and cso_active_48h:
        return "RED", 84, f"Moderate rain ({rain_48h:.0f}mm) + CSO active — only 16% safe"

    # Autumn/winter + CSO: 10-14% safe
    if not is_summer_spring and cso_active_48h:
        return "RED", 86, f"Autumn/winter + CSO active — only 10-14% safe"

    # >50h CSO discharge: 5% safe
    if cso_hours_48h > 50:
        return "RED", 95, f"Prolonged CSO discharge ({cso_hours_48h:.0f}h) — only 5% safe"

    # AMBER conditions — test first
    # Moderate rain without CSO: 55% safe
    if rain_48h > 2:
        return "AMBER", 55, f"Moderate rain ({rain_48h:.0f}mm/48h) — 55% safe, test first"

    # 1-2 dry days + CSO: 16% safe
    if dry_days <= 2 and cso_active_48h:
        return "AMBER", 84, f"Recent rain ({dry_days}d ago) + CSO active — only 16% safe, test first"

    # Autumn/winter without CSO: 32-33% safe
    if not is_summer_spring:
        return "AMBER", 67, f"Autumn/winter — only 32% safe even when dry, test first"

    # 1-2 dry days without CSO: 76% safe — borderline
    if dry_days <= 2:
        return "AMBER", 24, f"{dry_days} dry day(s) — 76% safe but recent rain, consider testing"

    # Single-river CSO active but dry conditions and summer/spring: 33-46% safe
    if cso_active_48h:
        river_str = f" ({river_names[0]})" if river_names else ""
        return "AMBER", 45, f"CSO active upstream{river_str} despite dry weather — 33-46% safe, consider testing"

    # GREEN conditions — go with confidence
    # Dry (≤2mm) + 3+ dry days + no CSO + summer/spring: 77-81% safe
    if dry_days >= 6:
        return "GREEN", 81, f"Dry conditions ({dry_days}d), no CSO, {season} — 81% safe"

    if dry_days >= 3:
        return "GREEN", 77, f"Dry conditions ({dry_days}d), no CSO, {season} — 77% safe"

    return "AMBER", 50, "Borderline conditions — consider testing"


# === VALIDATION ===

def validate_model():
    """Test model against historical data and report accuracy."""
    with open("thameswatch-analysis/thameswatch_correlation_with_cso.csv") as f:
        rows = list(csv.DictReader(f))

    results = defaultdict(lambda: {"total": 0, "safe": 0, "dangerous": 0})

    for row in rows:
        ec = float(row["ec"])
        rain_48h = float(row["rain_48h"])
        dry_days = float(row["dry_days"])
        season = row["season"]
        cso_active = row["cso_active_48h"] == "True"
        cso_hours = float(row["cso_hours_48h"]) if row["cso_hours_48h"] else 0

        cso_monitors = row.get("cso_active_monitors", "")
        level, confidence, explanation = assess_safety(
            rain_48h, dry_days, season, cso_active, cso_hours, cso_monitors
        )

        is_safe = ec <= 500
        is_dangerous = ec > 2000

        results[level]["total"] += 1
        if is_safe:
            results[level]["safe"] += 1
        if is_dangerous:
            results[level]["dangerous"] += 1

    print("=== Traffic Light Model v2 — Validation against 207 historical samples ===\n")

    for level in ["GREEN", "AMBER", "RED"]:
        r = results[level]
        if r["total"] == 0:
            continue
        safe_pct = r["safe"] / r["total"] * 100
        danger_pct = r["dangerous"] / r["total"] * 100
        print(f"  {level:>6s}: n={r['total']:>3}  |  actually safe (EC≤500): {safe_pct:>4.0f}%  |  actually dangerous (EC>2000): {danger_pct:>4.0f}%")

    print()

    # Compare with v1 (no CSO)
    print("=== Comparison: v1 (rain+season only) vs v2 (rain+season+CSO) ===\n")

    v1_results = defaultdict(lambda: {"total": 0, "safe": 0, "dangerous": 0})
    for row in rows:
        ec = float(row["ec"])
        rain_48h = float(row["rain_48h"])
        dry_days = float(row["dry_days"])
        season = row["season"]

        # v1 model (no CSO awareness)
        is_summer_spring = season in ("spring", "summer")
        if rain_48h > 10 or dry_days == 0:
            v1_level = "RED"
        elif rain_48h > 2 or not is_summer_spring or dry_days <= 2:
            v1_level = "AMBER"
        else:
            v1_level = "GREEN"

        is_safe = ec <= 500
        is_dangerous = ec > 2000
        v1_results[v1_level]["total"] += 1
        if is_safe:
            v1_results[v1_level]["safe"] += 1
        if is_dangerous:
            v1_results[v1_level]["dangerous"] += 1

    print("  v1 (no CSO):")
    for level in ["GREEN", "AMBER", "RED"]:
        r = v1_results[level]
        if r["total"] == 0:
            continue
        safe_pct = r["safe"] / r["total"] * 100
        danger_pct = r["dangerous"] / r["total"] * 100
        print(f"    {level:>6s}: n={r['total']:>3}  |  safe: {safe_pct:>4.0f}%  |  dangerous: {danger_pct:>4.0f}%")

    print("\n  v2 (with CSO):")
    for level in ["GREEN", "AMBER", "RED"]:
        r = results[level]
        if r["total"] == 0:
            continue
        safe_pct = r["safe"] / r["total"] * 100
        danger_pct = r["dangerous"] / r["total"] * 100
        print(f"    {level:>6s}: n={r['total']:>3}  |  safe: {safe_pct:>4.0f}%  |  dangerous: {danger_pct:>4.0f}%")

    # Key metric: false sense of security (said GREEN but was dangerous)
    print("\n  Key safety metric — GREEN but actually dangerous (EC>2000):")
    v1_green_danger = v1_results["GREEN"]["dangerous"]
    v1_green_total = v1_results["GREEN"]["total"]
    v2_green_danger = results["GREEN"]["dangerous"]
    v2_green_total = results["GREEN"]["total"]
    print(f"    v1: {v1_green_danger}/{v1_green_total} ({v1_green_danger/v1_green_total*100:.1f}%)" if v1_green_total else "    v1: n/a")
    print(f"    v2: {v2_green_danger}/{v2_green_total} ({v2_green_danger/v2_green_total*100:.1f}%)" if v2_green_total else "    v2: n/a")

    # Multi-river analysis
    print("\n=== Multi-river CSO analysis (v2.1) ===\n")
    multi_river_cases = []
    for row in rows:
        monitors = row.get("cso_active_monitors", "")
        n_systems, systems = count_active_river_systems(monitors)
        if n_systems >= 2:
            multi_river_cases.append(row)

    if multi_river_cases:
        ec_vals = [float(r["ec"]) for r in multi_river_cases]
        safe = sum(1 for v in ec_vals if v <= 500)
        danger = sum(1 for v in ec_vals if v > 2000)
        print(f"  Multi-river CSO events: {len(multi_river_cases)}")
        print(f"  Safe (EC≤500): {safe}/{len(multi_river_cases)} ({safe/len(multi_river_cases)*100:.0f}%)")
        print(f"  Dangerous (EC>2000): {danger}/{len(multi_river_cases)} ({danger/len(multi_river_cases)*100:.0f}%)")
        print(f"  Mean EC: {sum(ec_vals)/len(ec_vals):.0f}")
        print(f"  → Multi-river = automatic RED with 100% confidence")


# === INTERACTIVE MODE ===

def interactive():
    print("=== ThamesWatch Safety Check v2.1 ===\n")

    rain_48h = float(input("Rainfall in last 48h (mm): "))
    dry_days = int(input("Days since last rain >2mm: "))
    season = input("Season (spring/summer/autumn/winter): ").lower()
    cso_input = input("CSO discharging upstream? (yes/no/unknown): ").lower()
    cso_active = cso_input in ("yes", "y", "true")
    cso_hours = 0
    cso_monitors_str = ""
    if cso_active:
        try:
            cso_hours = float(input("Approximate CSO discharge hours (or 0 if unknown): ") or "0")
        except ValueError:
            cso_hours = 0
        print("Which rivers have active CSOs? (comma-separated, or 'unknown')")
        print("  Options: Wey, Mole, Thames, Minor")
        rivers_input = input("Rivers: ").strip().lower()
        if rivers_input and rivers_input != "unknown":
            # Build a fake monitors string that the classifier can parse
            river_map = {
                "wey": "Weybridge(1h)",
                "mole": "Esher(1h)",
                "thames": "Kingston Main(1h)",
                "minor": "Commonside(1h)",
            }
            parts = [river_map[r.strip()] for r in rivers_input.split(",") if r.strip() in river_map]
            cso_monitors_str = "; ".join(parts)

    level, confidence, explanation = assess_safety(
        rain_48h, dry_days, season, cso_active, cso_hours, cso_monitors_str
    )

    colours = {"GREEN": "\033[92m", "AMBER": "\033[93m", "RED": "\033[91m"}
    reset = "\033[0m"

    print(f"\n{colours.get(level, '')}{level}{reset} — {explanation}")
    print(f"Confidence: {confidence}%")

    if level == "GREEN":
        print("\nGo with confidence. Standard precautions apply.")
    elif level == "AMBER":
        print("\nTest water before activity. Consider postponing if test unavailable.")
    else:
        print("\nDo not go on the water. Wait for conditions to improve.")


if __name__ == "__main__":
    if "--validate" in sys.argv:
        validate_model()
    else:
        interactive()
