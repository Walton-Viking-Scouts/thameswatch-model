#!/usr/bin/env python3
"""ThamesWatch prediction entry point — RED/AMBER/GREEN for every site.

Assembles a live snapshot (rain, flow, CSO), runs it through the traffic-light model,
and emits a human-readable report plus a versioned JSON artifact for downstream
consumers (e.g. a website). Replaces the hand-assembly of API calls that running the
model for "today" used to require.

Usage:
    python3 scripts/predict.py                          # all sites, text report
    python3 scripts/predict.py --site Teddington        # one site
    python3 scripts/predict.py --date 2026-05-10        # back-dated assessment
    python3 scripts/predict.py --json prediction.json   # also write a JSON artifact
    python3 scripts/predict.py --json -                 # JSON to stdout (no text)
    python3 scripts/predict.py --no-topup               # skip the CSV refresh (faster)
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root → import tw

import argparse
import json
import sys
from datetime import datetime, timezone

from tw import flood_monitoring
from tw.config import CSO_MONITORS, SITE_LIVE_FLOW_GAUGE
from tw.model import assess_safety, SITE_CSO_RELEVANCE
from tw.snapshot import build_snapshot, build_upstream_watch

# monitor name -> river_system, for grouping active CSOs into the systems each site cares
# about (the "Why" detail lists only site-relevant discharges).
_CSO_SYSTEM = {m.name: m.river_system for m in CSO_MONITORS}

SCHEMA_VERSION = 1
MODEL_VERSION = "v3"

LEVEL_ICON = {"GREEN": "🟢", "AMBER": "🟠", "RED": "🔴"}
LEVEL_LEGEND = ("🔴 do not go on the water · 🟠 test the water with an R-Card first · "
                "🟢 good to go")
EC_LEGEND = "safe = EC ≤ 500 · unsafe = EC > 500 · dangerous = EC > 2000 (cfu/100ml)"

# The workflow splices the live status into the README between these markers.
README_START = "<!-- PREDICTION:START -->"
README_END = "<!-- PREDICTION:END -->"


def _why_detail(s):
    """A specifics line for the verdict: site-relevant active CSOs (with discharge hours),
    notable rain, and any tributary surge — built from the snapshot's own inputs."""
    relevant = set(SITE_CSO_RELEVANCE.get(
        s.site, ["Wey", "Mole", "Thames", "Minor", "ThamesUpstream"]))
    # Collect one label per monitor, preferring a discharge-hours figure over a bare
    # "live" flag (a monitor can appear in both the 48h history and the current-status feed).
    mon_label = {}
    for entry in (s.cso_active_monitors_str or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        name = entry.split("(")[0].strip()
        system = _CSO_SYSTEM.get(name)
        if system is None or system not in relevant:
            continue  # not a monitor that can reach this site
        label = entry[entry.rindex("(") + 1:-1].strip() if entry.endswith(")") else ""
        cur = mon_label.get(name)
        if cur is None or (cur[1] in ("", "live") and label not in ("", "live")):
            mon_label[name] = (system, label)

    by_sys = {}
    for name, (system, label) in mon_label.items():
        disp = f"{name} (live)" if label == "live" else (f"{name} {label}".strip())
        by_sys.setdefault(system, []).append(disp)

    bits = [f"{sysname}: " + ", ".join(mons)
            for sysname in ("Wey", "Mole", "Thames", "ThamesUpstream", "Minor")
            if (mons := by_sys.get(sysname))]

    if s.rain_48h and s.rain_48h > 2:
        bits.append(f"rain {s.rain_48h:.0f}mm/48h")
    elif s.rain_7d and s.rain_7d > 15:
        bits.append(f"rain {s.rain_7d:.0f}mm/7d antecedent")

    ctx = s.upstream_ctx or {}
    for river, key in (("Wey", "wey"), ("Mole", "mole")):
        if river in relevant and ctx.get(f"{key}_rising"):
            f15 = ctx.get(f"{key}_flow_15min")
            bits.append(f"{river} flow rising{f' ({f15:.1f} m³/s)' if f15 else ''}")
    return " · ".join(bits)


def check_today(site=None, date=None, topup=True):
    """Build a snapshot, run the model per site, return a structured result dict."""
    snaps = build_snapshot(date, topup=topup)
    if site:
        if site not in snaps:
            raise SystemExit(f"unknown site '{site}' — known: {', '.join(snaps)}")
        snaps = {site: snaps[site]}

    # Live per-site flow (safety context) — only for a live "today" run, and fetched once
    # per gauge. Best-effort: a feed failure leaves the column blank, never aborts.
    today = datetime.now(timezone.utc).date().isoformat()
    is_today = next(iter(snaps.values())).date >= today
    _flow_cache = {}

    def _live_flow(site_name):
        gauge = SITE_LIVE_FLOW_GAUGE.get(site_name)
        if not is_today or not gauge:
            return None
        if gauge not in _flow_cache:
            try:
                _flow_cache[gauge], _ = flood_monitoring.latest_flow(gauge)
            except Exception:  # noqa: BLE001 — never abort a prediction on a flow fetch
                _flow_cache[gauge] = None
        return _flow_cache[gauge]

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
            "why_detail": _why_detail(s),
            "live_flow_m3s": _live_flow(name),
            "flow_gauge": SITE_LIVE_FLOW_GAUGE.get(name),
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

    resolved_date = next(iter(snaps.values())).date
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assessment_date": resolved_date,
        "model_version": MODEL_VERSION,
        "sites": sites_out,
        "upstream_watch": build_upstream_watch(resolved_date),
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
        flow = s.get("live_flow_m3s")
        flow_str = f"{flow:.0f} m3/s" if flow is not None else "  —  "
        lines.append(f"  {s['level']:6s} {s['site']:24s} {flow_str:>9s} {s['confidence']:>3}%  "
                      f"{s['explanation']}")
        if s.get("why_detail"):
            lines.append(f"         · {s['why_detail']}")
        for w in s["data_quality"]["warnings"]:
            lines.append(f"         ! {w}")
    lines.append("=" * 72)
    su = result["summary"]
    lines.append(f"  {su.get('GREEN', 0)} GREEN   {su.get('AMBER', 0)} AMBER   "
                  f"{su.get('RED', 0)} RED")
    lines.append(f"  ({EC_LEGEND})")

    uw = result.get("upstream_watch")
    if uw:
        lines.append("")
        lines.append(f"Upstream watch — headwater rain (arrives ~{uw['headwater_lag']} "
                      f"later) and each tributary's flow trend over the last 24h")
        for c in uw["catchments"]:
            pct = c["flow_change_pct"]
            trend = f"{pct:+d}%/24h" if pct is not None else "?"
            lines.append(f"  {c['catchment']:7s} {c['rain_5d_mm']:>5}mm/5d   "
                          f"{c['flow_station']:22s} {c['flow_m3s'] or 0:>6.1f} m3/s  "
                          f"{trend:>9s}  {c['status']}")
    return "\n".join(lines)


def render_markdown(result):
    """Render a result dict as a friendly markdown status block for the README."""
    lines = [
        "## Current water-safety status",
        "",
        f"Assessment for **{result['assessment_date']}** — "
        f"updated {result['generated_at']} (model {result['model_version']}).",
        "",
        "| | Site | Status | Flow (live) | Why this colour |",
        "|---|---|---|---|---|",
    ]
    for s in result["sites"]:
        icon = LEVEL_ICON.get(s["level"], "")
        flow = s.get("live_flow_m3s")
        flow_cell = f"{flow:.0f} m³/s" if flow is not None else "—"
        why = s["explanation"]
        if s.get("why_detail"):
            why += f"<br>{s['why_detail']}"
        lines.append(f"| {icon} | **{s['site']}** | {s['level']} | {flow_cell} | {why} |")
    su = result["summary"]
    lines += [
        "",
        f"**{su.get('GREEN', 0)} 🟢 GREEN · {su.get('AMBER', 0)} 🟠 AMBER · "
        f"{su.get('RED', 0)} 🔴 RED**",
        "",
        f"_{LEVEL_LEGEND}_",
        "",
        f"_{EC_LEGEND}_",
    ]
    uw = result.get("upstream_watch")
    if uw:
        bits = [f"{c['catchment']} {c['status']}" for c in uw["catchments"]]
        lines += ["", f"_Upstream watch (tributary flow, last 24h): "
                       f"{' · '.join(bits)}._"]
    lines += ["", "_Full reasoning and data quality in "
                   "[`prediction.json`](prediction.json); methodology in "
                   "[`EXEC-SUMMARY.md`](EXEC-SUMMARY.md)._"]
    return "\n".join(lines)


def update_readme(path, result):
    """Splice the live status block into the README between the marker comments."""
    with open(path) as f:
        text = f.read()
    if README_START not in text or README_END not in text:
        raise SystemExit(f"{path} is missing the {README_START} / {README_END} markers")
    head = text[:text.index(README_START) + len(README_START)]
    tail = text[text.index(README_END):]
    with open(path, "w") as f:
        f.write(f"{head}\n{render_markdown(result)}\n{tail}")


def main():
    parser = argparse.ArgumentParser(description="ThamesWatch water-safety prediction.")
    parser.add_argument("--site", help="assess a single site (default: all)")
    parser.add_argument("--date", help="ISO assessment date (default: today)")
    parser.add_argument("--json", dest="json_out",
                        help="write JSON to a path, or '-' for stdout")
    parser.add_argument("--readme", dest="readme_out",
                        help="splice the live status into a README markdown file")
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
    if args.readme_out:
        update_readme(args.readme_out, result)
        print(f"Updated {args.readme_out}")
    print(render_text(result))


if __name__ == "__main__":
    main()
