#!/usr/bin/env python3
"""ThamesWatch prediction entry point — RED/AMBER/GREEN for every site.

Assembles a live snapshot (rain, flow, CSO), runs it through the traffic-light model,
and emits a human-readable report plus a versioned JSON artifact for downstream
consumers (e.g. a website). Replaces the hand-assembly of API calls that running the
model for "today" used to require.

Usage:
    python3 predict.py                          # all sites, text report
    python3 predict.py --site Teddington        # one site
    python3 predict.py --date 2026-05-10        # back-dated assessment
    python3 predict.py --json prediction.json   # also write a JSON artifact
    python3 predict.py --json -                 # JSON to stdout (no text)
    python3 predict.py --no-topup               # skip the CSV refresh (faster)
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from traffic_light_model_v3 import assess_safety
from tw.snapshot import build_snapshot

SCHEMA_VERSION = 1
MODEL_VERSION = "v3"


def check_today(site=None, date=None, topup=True):
    """Build a snapshot, run the model per site, return a structured result dict."""
    snaps = build_snapshot(date, topup=topup)
    if site:
        if site not in snaps:
            raise SystemExit(f"unknown site '{site}' — known: {', '.join(snaps)}")
        snaps = {site: snaps[site]}

    sites_out = []
    summary = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for name, s in snaps.items():
        level, confidence, explanation = assess_safety(
            s.rain_48h, s.dry_days, s.season, s.cso_active_48h, s.cso_hours_48h,
            s.cso_active_monitors_str, s.site, s.flow_m3s, s.rain_7d, s.upstream_ctx)
        summary[level] = summary.get(level, 0) + 1
        sites_out.append({
            "site": name,
            "level": level,
            "confidence": confidence,
            "explanation": explanation,
            "inputs": {
                "rain_48h": s.rain_48h, "rain_7d": s.rain_7d, "dry_days": s.dry_days,
                "season": s.season, "flow_m3s": s.flow_m3s,
                "cso_active_48h": s.cso_active_48h, "cso_hours_48h": s.cso_hours_48h,
                "cso_active_monitors": s.cso_active_monitors_str,
                "upstream_ctx": s.upstream_ctx,
            },
            "data_quality": {
                "rain_station": s.rain_station,
                "flow_data_date": s.flow_data_date,
                "data_lag_days": s.data_lag_days,
                "warnings": s.warnings,
            },
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assessment_date": next(iter(snaps.values())).date,
        "model_version": MODEL_VERSION,
        "sites": sites_out,
        "summary": summary,
    }


def render_text(result):
    """Render a result dict as a plain-text report."""
    lines = [
        f"ThamesWatch water safety — {result['assessment_date']}  "
        f"(model {result['model_version']}, generated {result['generated_at']})",
        "=" * 72,
    ]
    for s in result["sites"]:
        lines.append(f"  {s['level']:6s} {s['site']:24s} {s['confidence']:>3}%  "
                      f"{s['explanation']}")
        for w in s["data_quality"]["warnings"]:
            lines.append(f"         ! {w}")
    lines.append("=" * 72)
    su = result["summary"]
    lines.append(f"  {su.get('GREEN', 0)} GREEN   {su.get('AMBER', 0)} AMBER   "
                  f"{su.get('RED', 0)} RED")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ThamesWatch water-safety prediction.")
    parser.add_argument("--site", help="assess a single site (default: all)")
    parser.add_argument("--date", help="ISO assessment date (default: today)")
    parser.add_argument("--json", dest="json_out",
                        help="write JSON to a path, or '-' for stdout")
    parser.add_argument("--no-topup", action="store_true",
                        help="skip refreshing the flow/rain CSVs")
    args = parser.parse_args()

    result = check_today(site=args.site, date=args.date, topup=not args.no_topup)

    if args.json_out == "-":
        print(json.dumps(result, indent=2))
        return
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote {args.json_out}")
    print(render_text(result))


if __name__ == "__main__":
    main()
