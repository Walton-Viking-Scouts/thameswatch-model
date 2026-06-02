#!/usr/bin/env python3
"""Fetch ThamesWatch water quality test results and write them to a CSV.

This is the calibration ground-truth fetcher. The EC/EI test results it pulls are
the only source of actual bacteria data on our stretch — everything else (rain, flow,
CSO) is enrichment layered on top. Before this script existed the results were pasted
by hand into build_correlation.py; this captures the endpoint so a calibration refresh
is one reproducible command.

API: ThamesWatch public API — https://thames-watch.uk/swagger
  GET /api/v1/locations                       — all test locations
  GET /api/v1/results/{locationId}            — results for a location (fromDate/toDate)
Public read endpoints need no authentication.

Usage:
    python3 scripts/fetch_thameswatch.py                       # full history -> thameswatch_results.csv
    python3 scripts/fetch_thameswatch.py --from 2026-03-13     # only results on/after a date
    python3 scripts/fetch_thameswatch.py --out latest.csv      # custom output path
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root → import tw

import argparse
import csv
import sys
from datetime import date

import requests

from tw.paths import data_file
from tw.thameswatch import fetch_locations, fetch_results

DEFAULT_FROM = "2024-01-01"  # earliest ThamesWatch data predates this; safe lower bound
DEFAULT_OUT = data_file("thameswatch_results.csv")

FIELDS = [
    "testLocationId", "locationName", "stationId", "latitude", "longitude",
    "testDate", "ec", "ecDescription", "ei", "eiDescription", "testType",
    "flowRate", "waterTemperature", "rainfall24h", "rainfall3d", "rainfall7d",
    "reference", "testResultId",
]


def main():
    parser = argparse.ArgumentParser(description="Fetch ThamesWatch test results to CSV.")
    parser.add_argument("--from", dest="from_date", default=DEFAULT_FROM,
                        help=f"ISO start date (default {DEFAULT_FROM})")
    parser.add_argument("--to", dest="to_date", default=date.today().isoformat(),
                        help="ISO end date (default today)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"output CSV path (default {DEFAULT_OUT})")
    args = parser.parse_args()

    print("Fetching locations from ThamesWatch API ...")
    locations = fetch_locations()
    print(f"  {len(locations)} locations")

    rows = []
    for loc in locations:
        loc_id = loc["testLocationId"]
        name = loc.get("name", "")
        results = fetch_results(loc_id, args.from_date, args.to_date)
        print(f"  {name:42s} {len(results):3d} results")
        for res in results:
            rows.append({
                "testLocationId": loc_id,
                "locationName": name,
                "stationId": loc.get("stationId") or "",
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "testDate": (res.get("testDate") or "")[:10],
                "ec": res.get("ec"),
                "ecDescription": res.get("ecDescription") or "",
                "ei": res.get("ei"),
                "eiDescription": res.get("eiDescription") or "",
                "testType": res.get("testType") or "",
                "flowRate": res.get("flowRate"),
                "waterTemperature": res.get("waterTemperature"),
                "rainfall24h": res.get("rainfall24h"),
                "rainfall3d": res.get("rainfall3d"),
                "rainfall7d": res.get("rainfall7d"),
                "reference": res.get("reference") or "",
                "testResultId": res.get("testResultId") or "",
            })

    rows.sort(key=lambda r: (r["locationName"], r["testDate"]))

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} results ({args.from_date} to {args.to_date}) -> {args.out}")
    if rows:
        dates = [r["testDate"] for r in rows if r["testDate"]]
        print(f"Date range in data: {min(dates)} to {max(dates)}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        sys.exit(1)
