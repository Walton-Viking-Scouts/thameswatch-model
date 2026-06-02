#!/usr/bin/env python3
"""Plot a site's recent E. coli test results against the model's daily RAG verdict.

Produces a chart: the model's RED/AMBER/GREEN run for every day (background bands),
with the actual ThamesWatch E. coli test results overlaid as points — so you can see
at a glance whether the traffic light tracked what the testing found.

Usage:
    python3 scripts/chart_site.py                       # Walton Wharf, last 8 weeks
    python3 scripts/chart_site.py --site Teddington --weeks 12 --out teddington.png
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root → import tw

import argparse
import csv
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from tw import config
from tw.enrichment import calc_rain_metrics, season_of
from tw.paths import data_file
from tw.thames_water import fetch_all_discharge_periods, was_cso_active, count_cso_hours
from tw.model import assess_safety, get_upstream_context

RAG_COLOUR = {"GREEN": "#3aa655", "AMBER": "#e8a317", "RED": "#d23b3b"}


def load_csv(path):
    out = {}
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("date"):
            continue
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description="Chart test results vs model RAG.")
    ap.add_argument("--site", default="Walton Wharf")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--end", help="ISO end date for the window (default: today)")
    ap.add_argument("--out", default="chart.png")
    args = ap.parse_args()

    site = config.SITES[args.site]
    end = (datetime.fromisoformat(args.end).date() if args.end
           else datetime.now(timezone.utc).date())
    start = end - timedelta(weeks=args.weeks)

    rain = load_csv(data_file(config.RAIN_CSV[site.rain_station_key]))
    walton_flow = load_csv(data_file("walton_flow.csv"))
    print("Fetching CSO discharge history ...")
    periods = fetch_all_discharge_periods()

    # Run the model for every day in the window.
    days, rags = [], []
    d = start
    while d <= end:
        ds = d.isoformat()
        m = calc_rain_metrics(rain, ds)
        check = datetime(d.year, d.month, d.day, 12)
        active, _ = was_cso_active(periods, check, 48)
        hrs, mons = count_cso_hours(periods, check, 48)
        mon_str = "; ".join(f"{n}({h}h)" for n, h in mons)
        level, _, _ = assess_safety(
            m["rain_48h"], m["dry_days"], season_of(ds), active, hrs, mon_str,
            args.site, walton_flow.get(ds), m["rain_7d"], get_upstream_context(ds))
        days.append(d)
        rags.append(level)
        d += timedelta(days=1)

    # Actual ThamesWatch test results in the window.
    tests = []
    for r in csv.DictReader(open(data_file("thameswatch_results.csv"))):
        if r["locationName"] == site.thameswatch_location and r["ec"]:
            td = datetime.strptime(r["testDate"][:10], "%Y-%m-%d").date()
            if start <= td <= end:
                tests.append((td, int(r["ec"])))
    tests.sort()

    # Plot.
    fig, ax = plt.subplots(figsize=(11, 5))
    for day, rag in zip(days, rags):
        ax.axvspan(day, day + timedelta(days=1), color=RAG_COLOUR[rag], alpha=0.30, lw=0)

    ax.axhline(500, color="#333", ls="--", lw=1)
    ax.text(days[0], 530, "safe limit (500)", fontsize=8, color="#333")
    ax.axhline(2000, color="#7a0000", ls=":", lw=1)
    ax.text(days[0], 2150, "dangerous (2000)", fontsize=8, color="#7a0000")

    if tests:
        tx = [t[0] for t in tests]
        ty = [t[1] for t in tests]
        ax.plot(tx, ty, "o-", color="#111", ms=8, lw=1.5, zorder=5, label="E. coli test result")
        for x, y in tests:
            ax.annotate(str(y), (x, y), textcoords="offset points", xytext=(0, 9),
                        ha="center", fontsize=8, fontweight="bold")

    ax.set_yscale("log")
    ax.set_ylim(30, 20000)
    ax.set_ylabel("E. coli (cfu / 100ml)")
    ax.set_xlim(start, end + timedelta(days=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.set_title(f"{args.site} — E. coli tests vs model traffic light, last {args.weeks} weeks")

    handles = [plt.Rectangle((0, 0), 1, 1, color=RAG_COLOUR[k], alpha=0.30)
               for k in ("GREEN", "AMBER", "RED")]
    labels = ["model GREEN", "model AMBER", "model RED"]
    ax.legend(handles + ax.get_legend_handles_labels()[0],
              labels + ax.get_legend_handles_labels()[1], loc="upper right", fontsize=8)

    fig.savefig(args.out, dpi=120, bbox_inches="tight")
    print(f"Wrote {args.out}  ({len(tests)} tests, {len(days)} days of model RAG)")


if __name__ == "__main__":
    main()
