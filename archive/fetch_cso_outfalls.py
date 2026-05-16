#!/usr/bin/env python3
"""Fetch Thames Water CSO outfalls discharging into the River Thames near our stretch (Chertsey to Teddington)."""

import json
import requests
import csv

API_ROOT = "https://api.thameswater.co.uk"
CURRENT_STATUS = "/opendata/v2/discharge/status"
API_LIMIT = 1000

def fetch_all_current_status():
    """Fetch current status of all EDM monitors, handling pagination."""
    url = API_ROOT + CURRENT_STATUS
    all_items = []
    offset = 0

    while True:
        params = {"limit": API_LIMIT, "offset": offset}
        print(f"Fetching offset {offset}...")
        r = requests.get(url, params=params)

        if r.status_code != 200:
            print(f"Error: {r.status_code} - {r.text[:200]}")
            break

        data = r.json()
        if "items" not in data or not data["items"]:
            print("No more items.")
            break

        items = data["items"]
        all_items.extend(items)
        print(f"  Got {len(items)} items (total: {len(all_items)})")

        if len(items) < API_LIMIT:
            break
        offset += API_LIMIT

    return all_items

def filter_thames_stretch(monitors):
    """Filter for monitors discharging into the Thames on our stretch (Chertsey to Teddington)."""
    # Approximate easting range for Chertsey (505000) to Teddington (517000)
    # With some buffer either side
    MIN_EASTING = 503000
    MAX_EASTING = 518000
    MIN_NORTHING = 160000  # South of Thames in this area
    MAX_NORTHING = 172000  # North of Thames in this area

    thames_monitors = []
    for m in monitors:
        watercourse = (m.get("receivingWaterCourse") or "").lower()
        x = m.get("x", 0) or 0
        y = m.get("y", 0) or 0

        # Check if it discharges into the Thames (various spellings)
        is_thames = any(t in watercourse for t in ["thames", "river thames"])

        # Check if within our geographic box
        in_range = (MIN_EASTING <= x <= MAX_EASTING and MIN_NORTHING <= y <= MAX_NORTHING)

        if is_thames and in_range:
            thames_monitors.append(m)

    return thames_monitors

def main():
    print("=== Fetching all Thames Water EDM monitors ===")
    all_monitors = fetch_all_current_status()
    print(f"\nTotal monitors: {len(all_monitors)}")

    # Show unique watercourse names containing "thames"
    watercourses = set()
    for m in all_monitors:
        wc = m.get("receivingWaterCourse", "")
        if wc and "thames" in wc.lower():
            watercourses.add(wc)
    print(f"\nWatercourses containing 'thames': {sorted(watercourses)}")

    # Filter for our stretch
    stretch_monitors = filter_thames_stretch(all_monitors)
    print(f"\nMonitors on our stretch (Chertsey-Teddington): {len(stretch_monitors)}")

    # Sort by easting (upstream to downstream)
    stretch_monitors.sort(key=lambda m: m.get("x", 0) or 0)

    # Print details
    print(f"\n{'Name':<45} {'Permit':<15} {'Watercourse':<25} {'Easting':>8} {'Northing':>8} {'Status':<20} {'48h Alert'}")
    print("-" * 150)
    for m in stretch_monitors:
        print(f"{(m.get('locationName','')[:44]):<45} "
              f"{(m.get('permitNumber','')):<15} "
              f"{(m.get('receivingWaterCourse','')[:24]):<25} "
              f"{m.get('x',''):>8} "
              f"{m.get('y',''):>8} "
              f"{(m.get('alertStatus','')):<20} "
              f"{m.get('alertPast48Hours','')}")

    # Save to CSV
    csv_path = "thameswatch-analysis/cso_outfalls_our_stretch.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "locationName", "permitNumber", "receivingWaterCourse",
            "x", "y", "alertStatus", "statusChanged",
            "mostRecentDischargeAlertStart", "mostRecentDischargeAlertStop",
            "alertPast48Hours"
        ])
        writer.writeheader()
        for m in stretch_monitors:
            writer.writerow({k: m.get(k, "") for k in writer.fieldnames})
    print(f"\nSaved to {csv_path}")

    # Also save full JSON for reference
    json_path = "thameswatch-analysis/cso_outfalls_our_stretch.json"
    with open(json_path, "w") as f:
        json.dump(stretch_monitors, f, indent=2)
    print(f"Saved JSON to {json_path}")

if __name__ == "__main__":
    main()
