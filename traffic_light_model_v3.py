#!/usr/bin/env python3
"""
ThamesWatch Traffic Light Model v3 — site-specific with flow + rain_7d

Changes from v2.1:
  - Site-specific assessment: each site has its own upstream pollution profile
  - River flow (Walton 3100TH) as site-specific dilution predictor
  - rain_7d (7-day antecedent rainfall) catches delayed headwater runoff
  - Site-relevant CSO filtering: Walton only sees Wey CSOs, Kingston sees Wey+Mole+Hogsmill
  - Separate GREEN thresholds per site based on historical false-positive rates

Geographic model:
    Chertsey ─── WALTON ─── Wey confluence ─── Mole confluence ─── KINGSTON ─── TEDDINGTON
                    ↑                              ↑                    ↑
              Wey CSOs                       Esher STW           Hogsmill STW
         (Ripley, Weybridge)              + Mole CSOs         (continuous effluent)

Flow impact by site (from actual Walton 3100TH data):
  - Teddington: strong predictor. <15 m3/s = 25% safe (RED). <20 = AMBER.
  - Kingston Albany: flow doesn't help — Hogsmill STW creates random spikes at all flows.
  - Walton: no simple dilution story — Wey tributary brings more contamination at higher flow.
  - Kingston HMT / Chertsey: clean at all flow levels.

Flow data source: EA Hydrology API, station 3100TH (River Thames at Walton)
  https://environment.data.gov.uk/hydrology/id/measures/b92a2ca3-4eb9-4a8f-b82f-8bbc2a1dfbc9-flow-m-86400-m3s-qualified/readings.json

Usage:
    python3 traffic_light_model_v3.py                    # Interactive mode
    python3 traffic_light_model_v3.py --validate         # Validate against historical data
    python3 traffic_light_model_v3.py --compare          # Compare v2 vs v3
"""

import csv
import sys
from collections import defaultdict


# === SITE PROFILES ===

# Which CSO river systems affect each site (based on geography)
# "ThamesUpstream" = storm overflows on the Thames mainstem above Chertsey (discovered by
# fetch_upstream_cso.py). They sit above the entire stretch, so they are relevant to every
# site. Until that discovery has run the system is never detected (no monitors carry the
# tag), so adding it here is inert.
SITE_CSO_RELEVANCE = {
    "Chertsey": ["Wey", "ThamesUpstream"],  # actually upstream of the Wey — ThamesUpstream is the true predictor
    "Walton Wharf": ["Wey", "ThamesUpstream"],  # Wey joins at Weybridge, just above Walton
    "Ditton's Bend": ["Wey", "Mole", "ThamesUpstream"],  # downstream of both confluences
    "Kingston Albany Reach": ["Wey", "Mole", "Thames", "ThamesUpstream"],  # gets everything + Hogsmill STW
    "Kingston HMT": ["Wey", "Mole", "ThamesUpstream"],  # upstream of Hogsmill — explains why it's cleaner
    "West Molesey": ["Wey", "Mole", "ThamesUpstream"],
    "Hampton Court Bridge": ["Wey", "Mole", "Thames", "ThamesUpstream"],
    "Teddington": ["Wey", "Mole", "Thames", "Minor", "ThamesUpstream"],  # gets absolutely everything
}

# Site risk tier based on historical GREEN performance
# Tier 1: reliably clean in GREEN conditions (>= 90% safe)
# Tier 2: mostly clean but occasional failures (70-89% safe)
# Tier 3: unreliable even in GREEN conditions (< 70% safe)
SITE_RISK_TIER = {
    "Chertsey": 1,          # 100% safe in GREEN (n=4), clean at all flows
    "Kingston HMT": 1,      # 100% safe in GREEN (n=13), upstream of Hogsmill outfall
    "Walton Wharf": 2,      # 89% safe in GREEN (n=38)
    "Kingston Albany Reach": 3,  # 70% safe in GREEN (n=23) — Hogsmill STW, chaotic at all flows
    "Teddington": 3,        # 57% safe in GREEN (n=7) — gets everything + flow-sensitive
    "Ditton's Bend": 3,     # 24% safe overall (mostly winter data)
}

DEFAULT_RISK_TIER = 2  # unknown sites get moderate treatment

# Site-specific flow thresholds (from actual Walton 3100TH correlation analysis)
# None = flow doesn't meaningfully predict safety at this site
SITE_FLOW_CONFIG = {
    "Teddington": {
        "red_below": 15,    # <15 m3/s: 25% safe (n=4) — continuous effluent dominates
        "amber_below": 20,  # <20 m3/s: insufficient dilution for upstream STW load
    },
    "Kingston Albany Reach": None,  # flow doesn't predict — Hogsmill STW creates random spikes
    "Walton Wharf": None,          # no simple dilution — Wey brings more contamination at higher flow
    "Kingston HMT": None,          # clean at all flows
    "Chertsey": None,              # clean at all flows
    "Ditton's Bend": {
        "red_below": 15,    # downstream of everything, assume similar to Teddington
        "amber_below": 20,
    },
}


# === CSO SYSTEM CLASSIFICATION ===

def count_active_river_systems(cso_active_monitors_str):
    """Classify active CSO monitors into river systems."""
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

    # Upstream-of-Chertsey Thames monitors are discovered at runtime (config), so match
    # by their exact names rather than hard-coded keywords. Empty set => no-op.
    from tw.config import UPSTREAM_THAMES_NAMES
    if any(name and name in cso_active_monitors_str for name in UPSTREAM_THAMES_NAMES):
        systems.add("ThamesUpstream")

    return len(systems), sorted(systems)


def count_active_monitors(cso_active_monitors_str):
    """
    Count individual active CSO monitors (not river systems).

    The monitors string looks like: "Amyand Park Road(48.0h); Kingston Main(24.5h)"
    Each semicolon-separated entry is one monitor.

    Data shows CSO count is a powerful predictor:
      0 monitors: mean EC=605, 72% safe
      1 monitor:  mean EC=1,059, 48% safe
      2-3:        mean EC=1,983, 7% safe
      4+:         mean EC=3,411, 0% safe, 67% dangerous
    """
    if not cso_active_monitors_str:
        return 0
    return len([m for m in cso_active_monitors_str.split(";") if m.strip()])


def filter_relevant_cso(site, cso_active_monitors_str):
    """
    Filter CSO monitors to only those that affect this site.
    Walton doesn't care about Mole CSOs — they're downstream.
    Kingston cares about everything.
    """
    if not cso_active_monitors_str:
        return False, 0, ""

    relevant_systems = SITE_CSO_RELEVANCE.get(site, ["Wey", "Mole", "Thames", "Minor"])
    _, all_systems = count_active_river_systems(cso_active_monitors_str)

    # Filter to only relevant systems
    relevant_active = [s for s in all_systems if s in relevant_systems]

    if not relevant_active:
        return False, 0, ""

    return True, len(relevant_active), ", ".join(relevant_active)


# === CORE MODEL ===

def assess_safety(rain_48h, dry_days, season, cso_active_48h, cso_hours_48h=0,
                  cso_active_monitors_str="", site="", flow_m3s=None, rain_7d=None,
                  upstream_ctx=None):
    """
    Returns (level, confidence, explanation) where level is GREEN/AMBER/RED.

    v3 additions over v2.1:
    - Site-specific CSO relevance filtering
    - Flow-based dilution assessment (site-specific thresholds)
    - rain_7d for delayed headwater runoff detection
    - Site risk tier adjustments
    - Tributary surge detection (Wey/Mole flow rising >30% in 24h)
    - Upstream context from Wey (3090TH), Mole (3290TH), Staines (2900TH), Reading (2200TH)
    """
    is_summer_spring = season in ("spring", "summer")
    risk_tier = SITE_RISK_TIER.get(site, DEFAULT_RISK_TIER)

    # Filter CSOs to only those relevant to this site
    if site and cso_active_monitors_str:
        site_cso_active, site_cso_count, site_cso_systems = filter_relevant_cso(
            site, cso_active_monitors_str
        )
    else:
        site_cso_active = cso_active_48h
        site_cso_count = count_active_river_systems(cso_active_monitors_str)[0]
        site_cso_systems = ""

    # Use site-filtered CSO for multi-river check
    multi_river = site_cso_count >= 2

    # Count individual active monitors (not just river systems)
    monitor_count = count_active_monitors(cso_active_monitors_str)

    # === RED conditions ===

    # Multi-river CSO relevant to this site
    if multi_river:
        return "RED", 100, f"Multiple river CSOs active ({site_cso_systems}) — 0% safe historically"

    # === NEW in v3: CSO count — more monitors active = worse ===
    # 4+ monitors: 0% safe, 67% dangerous, mean EC=3,411
    if monitor_count >= 4:
        return "RED", 100, f"{monitor_count} CSO monitors discharging — 0% safe, 67% dangerous historically"

    # 2-3 monitors: 7% safe, 43% dangerous, mean EC=1,983
    if monitor_count >= 2:
        return "RED", 93, f"{monitor_count} CSO monitors discharging — only 7% safe historically"

    # Heavy rain
    if rain_48h > 10:
        return "RED", 95, f"Heavy rain ({rain_48h:.0f}mm/48h) — only 5-20% safe"

    # Rained today + relevant CSO
    if dry_days == 0 and site_cso_active:
        return "RED", 89, f"Rain today + CSO discharging upstream — only 11% safe"

    # Rained today
    if dry_days == 0:
        return "RED", 65, f"Rained today — only 35% safe even without CSO"

    # Moderate rain + relevant CSO
    if rain_48h > 2 and site_cso_active:
        return "RED", 84, f"Moderate rain ({rain_48h:.0f}mm) + CSO active — only 16% safe"

    # Autumn/winter + CSO
    if not is_summer_spring and site_cso_active:
        return "RED", 86, f"Autumn/winter + CSO active — only 10-14% safe"

    # Prolonged CSO
    if cso_hours_48h > 50 and site_cso_active:
        return "RED", 95, f"Prolonged CSO discharge ({cso_hours_48h:.0f}h) — only 5% safe"

    # === NEW in v3: Site-specific flow rules ===
    # Flow impact varies dramatically by site — only apply where data supports it
    flow_config = SITE_FLOW_CONFIG.get(site)
    if flow_m3s is not None and flow_config is not None:
        if flow_m3s < flow_config["red_below"]:
            return "RED", 85, (
                f"Very low flow ({flow_m3s:.0f} m3/s) at {site} — "
                f"only 25% safe below {flow_config['red_below']} m3/s, "
                f"continuous upstream effluent not diluted"
            )

    # === AMBER conditions ===

    # Moderate rain without CSO
    if rain_48h > 2:
        return "AMBER", 55, f"Moderate rain ({rain_48h:.0f}mm/48h) — 55% safe, test first"

    # Recent rain + relevant CSO
    if dry_days <= 2 and site_cso_active:
        return "AMBER", 84, f"Recent rain ({dry_days}d ago) + CSO active — only 16% safe, test first"

    # Autumn/winter
    if not is_summer_spring:
        return "AMBER", 67, f"Autumn/winter — only 32% safe even when dry, test first"

    # Recent rain
    if dry_days <= 2:
        return "AMBER", 24, f"{dry_days} dry day(s) — 76% safe but recent rain, consider testing"

    # Single-river CSO active
    if site_cso_active:
        return "AMBER", 45, f"CSO active upstream ({site_cso_systems}) — 33-46% safe, consider testing"

    # === NEW in v3: Site-specific flow AMBER ===
    if flow_m3s is not None and flow_config is not None:
        if flow_m3s < flow_config["amber_below"]:
            return "AMBER", 60, (
                f"Low flow ({flow_m3s:.0f} m3/s) at {site} — "
                f"insufficient dilution below {flow_config['amber_below']} m3/s, test first"
            )

    # === NEW in v3: Tributary surge detection ===
    # A rising Wey or Mole (>30% in 24h) signals upstream rainfall flushing CSOs
    # even if local rain is zero. The surge carries contamination downstream.
    if upstream_ctx:
        if site in ("Walton Wharf", "Chertsey") and upstream_ctx.get("wey_rising"):
            return "AMBER", 55, (
                f"Wey flow rising sharply (upstream rainfall flush) — "
                f"Wey is {upstream_ctx['wey_pct']:.0f}% of Walton flow, test first"
            )
        if site in ("Kingston Albany Reach", "Kingston HMT", "Teddington", "Ditton's Bend"):
            if upstream_ctx.get("wey_rising") or upstream_ctx.get("mole_rising"):
                rivers = []
                if upstream_ctx.get("wey_rising"):
                    rivers.append("Wey")
                if upstream_ctx.get("mole_rising"):
                    rivers.append("Mole")
                return "AMBER", 55, (
                    f"{' + '.join(rivers)} flow rising sharply (upstream flush) — test first"
                )

    # === NEW in v3: Heavy antecedent rain (7d) — delayed headwater runoff ===
    if rain_7d is not None and rain_7d > 15:
        return "AMBER", 45, f"Heavy rain in past week ({rain_7d:.0f}mm/7d) — delayed runoff possible, test first"

    # === NEW in v3: Tier 3 sites are never truly GREEN ===
    # Kingston Albany Reach: Hogsmill STW creates random spikes at all flows (70% safe in GREEN)
    # Teddington: gets all upstream pollution + flow-sensitive (57% safe in GREEN)
    if risk_tier == 3:
        return "AMBER", 55, f"{site} has elevated baseline from continuous upstream effluent — test first"

    # === GREEN conditions ===

    if dry_days >= 6:
        return "GREEN", 85, f"Dry conditions ({dry_days}d), no CSO, {season} — safe"

    if dry_days >= 3:
        return "GREEN", 80, f"Dry conditions ({dry_days}d), no CSO, {season} — safe"

    return "AMBER", 50, "Borderline conditions — consider testing"


# === VALIDATION ===

def load_data():
    from tw.paths import data_file
    with open(data_file("thameswatch_correlation_with_cso.csv")) as f:
        return list(csv.DictReader(f))


def run_v2(row):
    """v2.1 model for comparison."""
    rain_48h = float(row["rain_48h"])
    dry_days = float(row["dry_days"])
    season = row["season"]
    cso_active = row["cso_active_48h"] == "True"
    cso_hours = float(row["cso_hours_48h"]) if row["cso_hours_48h"] else 0
    monitors = row.get("cso_active_monitors", "")

    is_ss = season in ("spring", "summer")
    mc, rn = count_active_river_systems(monitors)

    if mc >= 2: return "RED"
    if rain_48h > 10: return "RED"
    if dry_days == 0 and cso_active: return "RED"
    if dry_days == 0: return "RED"
    if rain_48h > 2 and cso_active: return "RED"
    if not is_ss and cso_active: return "RED"
    if cso_hours > 50: return "RED"
    if rain_48h > 2: return "AMBER"
    if dry_days <= 2 and cso_active: return "AMBER"
    if not is_ss: return "AMBER"
    if dry_days <= 2: return "AMBER"
    if cso_active: return "AMBER"
    if dry_days >= 6: return "GREEN"
    if dry_days >= 3: return "GREEN"
    return "AMBER"


def _load_flow_csv(filename):
    """Load a flow CSV (date,flow_m3s) into a dict."""
    import os
    from tw.paths import data_file
    flow_file = data_file(filename)
    flow = {}
    if os.path.exists(flow_file):
        with open(flow_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("date"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        flow[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    return flow


# Module-level flow caches
_FLOW_CACHE = {}

FLOW_FILES = {
    "walton": "walton_flow.csv",           # 3100TH — Thames at Walton (our stretch)
    "wey": "wey_weybridge_flow.csv",       # 3090TH — Wey at confluence (909 km2 catchment)
    "mole": "mole_esher_flow.csv",         # 3290TH — Mole at confluence
    "staines": "thames_staines_flow.csv",  # 2900TH — Thames upstream of Wey confluence
    "reading": "thames_reading_flow.csv",  # 2200TH — Thames at Reading (~50h upstream)
}


def get_flow(name):
    """Get cached flow data for a station."""
    if name not in _FLOW_CACHE:
        filename = FLOW_FILES.get(name)
        if filename:
            _FLOW_CACHE[name] = _load_flow_csv(filename)
        else:
            _FLOW_CACHE[name] = {}
    return _FLOW_CACHE[name]


def get_walton_flow():
    return get_flow("walton")


def get_upstream_context(date):
    """
    Build upstream flow context for a given date.

    Returns dict with:
    - walton_flow: total flow at Walton (m3/s)
    - wey_flow: Wey contribution (m3/s)
    - mole_flow: Mole contribution (m3/s)
    - wey_pct: Wey as % of Walton flow
    - mole_pct: Mole as % of Walton flow
    - wey_rising: True if Wey flow rose >30% in 24h (CSO flush signal)
    - mole_rising: True if Mole flow rose >30% in 24h
    """
    from datetime import datetime, timedelta

    walton = get_flow("walton")
    wey = get_flow("wey")
    mole = get_flow("mole")

    w = walton.get(date, 0)
    wy = wey.get(date, 0)
    mo = mole.get(date, 0)

    prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    wy_prev = wey.get(prev_date, 0)
    mo_prev = mole.get(prev_date, 0)

    return {
        "walton_flow": w,
        "wey_flow": wy,
        "mole_flow": mo,
        "wey_pct": (wy / w * 100) if w > 0 else 0,
        "mole_pct": (mo / w * 100) if w > 0 else 0,
        "wey_rising": wy_prev > 0 and wy > wy_prev * 1.3,
        "mole_rising": mo_prev > 0 and mo > mo_prev * 1.3,
    }


def run_v3(row):
    """v3 model with actual Walton flow data."""
    rain_48h = float(row["rain_48h"])
    dry_days = float(row["dry_days"])
    season = row["season"]
    cso_active = row["cso_active_48h"] == "True"
    cso_hours = float(row["cso_hours_48h"]) if row["cso_hours_48h"] else 0
    monitors = row.get("cso_active_monitors", "")
    site = row["site"]
    rain_7d = float(row["rain_7d"]) if row.get("rain_7d") else None

    # Look up actual flow from Walton 3100TH
    flow_data = get_walton_flow()
    flow_m3s = flow_data.get(row["date"])

    # Build upstream context from tributary and Thames flow data
    upstream_ctx = get_upstream_context(row["date"])

    result = assess_safety(
        rain_48h, dry_days, season, cso_active, cso_hours,
        monitors, site, flow_m3s, rain_7d, upstream_ctx
    )
    return result[0]


def validate_model():
    """Compare v2 and v3 against historical data."""
    rows = load_data()

    v2_results = defaultdict(lambda: {"total": 0, "safe": 0, "unsafe500": 0, "dangerous": 0})
    v3_results = defaultdict(lambda: {"total": 0, "safe": 0, "unsafe500": 0, "dangerous": 0})
    v3_site_results = defaultdict(lambda: defaultdict(
        lambda: {"total": 0, "safe": 0, "unsafe500": 0, "dangerous": 0}
    ))

    changes = []

    for row in rows:
        ec = float(row["ec"])
        site = row["site"]
        is_safe = ec <= 500
        is_unsafe500 = ec > 500
        is_dangerous = ec > 2000

        v2_level = run_v2(row)
        v3_level = run_v3(row)

        for version, level, results in [("v2", v2_level, v2_results), ("v3", v3_level, v3_results)]:
            results[level]["total"] += 1
            if is_safe:
                results[level]["safe"] += 1
            if is_unsafe500:
                results[level]["unsafe500"] += 1
            if is_dangerous:
                results[level]["dangerous"] += 1

        v3_site_results[site][v3_level]["total"] += 1
        if is_safe:
            v3_site_results[site][v3_level]["safe"] += 1
        if is_unsafe500:
            v3_site_results[site][v3_level]["unsafe500"] += 1

        if v2_level != v3_level:
            changes.append({
                "site": site, "date": row["date"], "ec": ec,
                "v2": v2_level, "v3": v3_level,
                "rain_48h": float(row["rain_48h"]),
                "dry_days": float(row["dry_days"]),
                "rain_7d": float(row["rain_7d"]) if row.get("rain_7d") else None,
            })

    # Overall comparison
    print(f"=== v2.1 vs v3 — Overall ({len(rows)} samples, EC>500 = unsafe) ===\n")
    for version, results in [("v2.1", v2_results), ("v3 ", v3_results)]:
        print(f"  {version}:")
        for level in ["GREEN", "AMBER", "RED"]:
            r = results[level]
            if r["total"] == 0:
                continue
            safe_pct = r["safe"] / r["total"] * 100
            unsafe_pct = r["unsafe500"] / r["total"] * 100
            danger_pct = r["dangerous"] / r["total"] * 100
            print(f"    {level:>6s}: n={r['total']:>3}  |  safe (≤500): {safe_pct:>4.0f}%  |  unsafe (>500): {unsafe_pct:>4.0f}%  |  dangerous (>2000): {danger_pct:>4.0f}%")
        print()

    # Key metric
    print("  Key safety metric — GREEN but unsafe (EC>500):")
    v2_gu = v2_results["GREEN"]["unsafe500"]
    v2_gt = v2_results["GREEN"]["total"]
    v3_gu = v3_results["GREEN"]["unsafe500"]
    v3_gt = v3_results["GREEN"]["total"]
    if v2_gt:
        print(f"    v2.1: {v2_gu}/{v2_gt} ({v2_gu/v2_gt*100:.0f}%)")
    if v3_gt:
        print(f"    v3:   {v3_gu}/{v3_gt} ({v3_gu/v3_gt*100:.0f}%)")
    print()

    # Per-site v3 results
    print("=== v3 — Per-site GREEN performance ===\n")
    for site in sorted(v3_site_results.keys()):
        sr = v3_site_results[site]
        for level in ["GREEN", "AMBER", "RED"]:
            r = sr[level]
            if r["total"] == 0:
                continue
            safe_pct = r["safe"] / r["total"] * 100
            unsafe_pct = r["unsafe500"] / r["total"] * 100
            print(f"  {site:30s} {level:>6s}: n={r['total']:>3}  safe={safe_pct:>4.0f}%  unsafe={unsafe_pct:>4.0f}%")
        print()

    # Show what changed
    print(f"=== Changes from v2.1 to v3 ({len(changes)} samples reclassified) ===\n")
    for c in sorted(changes, key=lambda x: -x["ec"]):
        direction = "↑ safer" if ["RED", "AMBER", "GREEN"].index(c["v3"]) > ["RED", "AMBER", "GREEN"].index(c["v2"]) else "↓ stricter"
        correct = "✓" if (c["v3"] != "GREEN" and c["ec"] > 500) or (c["v3"] == "GREEN" and c["ec"] <= 500) else "✗"
        r7d = f"  rain7d={c['rain_7d']:.0f}" if c["rain_7d"] else ""
        print(f"  {correct} {c['site']:30s} {c['date']}  EC={c['ec']:>5.0f}  {c['v2']:>5s} → {c['v3']:>5s}  ({direction}){r7d}")


# === INTERACTIVE MODE ===

def interactive():
    print("=== ThamesWatch Safety Check v3 — Site-Specific ===\n")

    # Site selection
    print("Sites:")
    sites = sorted(SITE_RISK_TIER.keys())
    for i, s in enumerate(sites, 1):
        tier = SITE_RISK_TIER[s]
        tier_label = {1: "low risk", 2: "moderate", 3: "elevated baseline"}[tier]
        print(f"  {i}. {s} ({tier_label})")
    print(f"  {len(sites)+1}. Other / unknown")
    choice = input("\nSite number: ").strip()
    try:
        idx = int(choice) - 1
        site = sites[idx] if idx < len(sites) else ""
    except (ValueError, IndexError):
        site = ""

    rain_48h = float(input("Rainfall in last 48h (mm): "))
    dry_days = int(input("Days since last rain >2mm: "))
    season = input("Season (spring/summer/autumn/winter): ").lower()
    rain_7d = float(input("Rainfall in last 7 days (mm, or 0 if unknown): ") or "0")

    # Flow
    flow_input = input("River flow at Walton m3/s (or press enter if unknown): ").strip()
    flow_m3s = float(flow_input) if flow_input else None

    # CSO
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

        relevant = SITE_CSO_RELEVANCE.get(site, ["Wey", "Mole", "Thames", "Minor"])
        print(f"  Relevant to {site or 'this site'}: {', '.join(relevant)}")
        rivers_input = input("Rivers: ").strip().lower()
        if rivers_input and rivers_input != "unknown":
            river_map = {
                "wey": "Weybridge(1h)", "mole": "Esher(1h)",
                "thames": "Kingston Main(1h)", "minor": "Commonside(1h)",
            }
            parts = [river_map[r.strip()] for r in rivers_input.split(",") if r.strip() in river_map]
            cso_monitors_str = "; ".join(parts)

    level, confidence, explanation = assess_safety(
        rain_48h, dry_days, season, cso_active, cso_hours,
        cso_monitors_str, site, flow_m3s, rain_7d if rain_7d else None
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
    if "--validate" in sys.argv or "--compare" in sys.argv:
        validate_model()
    else:
        interactive()
