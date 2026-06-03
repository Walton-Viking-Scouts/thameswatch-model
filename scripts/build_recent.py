#!/usr/bin/env python3
"""Emit recent.json — the last 96 h of rain, river flow and CSO discharge per site, for
the website's "storm panel" (rainfall bars → sewage-overflow timeline → river-flow line).

Companion to predict.py: prediction.json is the current RED/AMBER/GREEN verdict;
recent.json is the recent time-series behind it. Run by the same workflow and committed
alongside, so a web page can draw the chart from a static file (no live API calls).

    python3 scripts/build_recent.py --json recent.json

Shape (compact): rain is the shared Hogsmill gauge; flows are keyed by gauge and
referenced per site; cso is the per-site list of discharge intervals (relevant monitors
only). All timestamps are ISO-8601 UTC.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root → import tw

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from tw import flood_monitoring
from tw.config import EA_STATIONS, EA_HYDROLOGY_ROOT, SITES, SITE_LIVE_FLOW_GAUGE, CSO_MONITORS
from tw.ea_hydrology import _get
from tw.model import SITE_CSO_RELEVANCE
from tw.thames_water import fetch_monitor_history, build_discharge_periods

WINDOW_H = 96


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rain_hourly(start):
    """Hogsmill 15-minute rain aggregated to hourly totals — [{t, mm}, ...]."""
    mid = EA_STATIONS["hogsmill_rain"].measure_id.replace("-86400-", "-900-")
    r = _get(f"{EA_HYDROLOGY_ROOT}/id/measures/{mid}/readings.json",
             {"mineq-date": start.date().isoformat(), "_limit": 5000, "_sort": "-dateTime"})
    hourly = defaultdict(float)
    for it in r.json().get("items", []):
        dt = datetime.fromisoformat(it["dateTime"])
        if dt >= start:
            hourly[dt.replace(minute=0, second=0, microsecond=0)] += it.get("value") or 0
    return [{"t": _iso(t), "mm": round(hourly[t], 2)} for t in sorted(hourly)]


def flow_hourly(gauge, start):
    """Live 15-minute flow at a gauge, averaged to hourly — [{t, m3s}, ...]."""
    try:
        raw = flood_monitoring.fetch_15min_flow(gauge, hours=WINDOW_H)
    except Exception:  # noqa: BLE001 — a missing gauge just yields an empty series
        return []
    buckets = defaultdict(list)
    for dt_s, v in raw:
        dt = datetime.fromisoformat(dt_s.replace("Z", ""))
        if dt >= start:
            buckets[dt.replace(minute=0, second=0, microsecond=0)].append(v)
    return [{"t": _iso(t), "m3s": round(sum(vs) / len(vs), 2)} for t, vs in sorted(buckets.items())]


def main():
    ap = argparse.ArgumentParser(description="Emit recent.json for the storm panel.")
    ap.add_argument("--json", dest="out", default="recent.json")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(hours=WINDOW_H)

    rain = rain_hourly(start)

    # Fetch each unique flow gauge and each relevant monitor once, then assemble per site.
    flows = {g: flow_hourly(g, start) for g in sorted(set(SITE_LIVE_FLOW_GAUGE.values()))}
    relevant = {m.name for site, sys in SITE_CSO_RELEVANCE.items()
                for m in CSO_MONITORS if m.river_system in sys}
    periods = {}
    for name in sorted(relevant):
        try:
            periods[name] = build_discharge_periods(fetch_monitor_history(name), now=now)
        except Exception:  # noqa: BLE001
            periods[name] = []

    sites_out = {}
    for site in SITES:
        systems = set(SITE_CSO_RELEVANCE.get(site, []))
        cso = []
        for m in CSO_MONITORS:
            if m.river_system not in systems:
                continue
            for st, en in periods.get(m.name, []):
                en = min(en, now)
                if en >= start and st < now:
                    cso.append({"monitor": m.name, "system": m.river_system,
                                "start": _iso(max(st, start)), "stop": _iso(en)})
        cso.sort(key=lambda e: e["start"])
        sites_out[site] = {"flow_gauge": SITE_LIVE_FLOW_GAUGE.get(site), "cso": cso}

    out = {
        "generated_at": _iso(now),
        "window_hours": WINDOW_H,
        "rain_gauge": "Hogsmill (Kingston)",
        "rain": rain,
        "flows": flows,
        "sites": sites_out,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    n_cso = sum(len(v["cso"]) for v in sites_out.values())
    print(f"wrote {args.out}: {len(rain)}h rain, {len(flows)} flow gauges, "
          f"{len(sites_out)} sites, {n_cso} cso intervals")


if __name__ == "__main__":
    main()
