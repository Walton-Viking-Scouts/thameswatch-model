#!/usr/bin/env python3
"""Explore all Thames Water EDM monitors to understand what's near our stretch."""

import requests
import json

API_ROOT = "https://api.thameswater.co.uk"
CURRENT_STATUS = "/opendata/v2/discharge/status"
API_LIMIT = 1000

def fetch_all():
    url = API_ROOT + CURRENT_STATUS
    all_items = []
    offset = 0
    while True:
        r = requests.get(url, params={"limit": API_LIMIT, "offset": offset})
        if r.status_code != 200:
            break
        data = r.json()
        if "items" not in data or not data["items"]:
            break
        all_items.extend(data["items"])
        if len(data["items"]) < API_LIMIT:
            break
        offset += API_LIMIT
    return all_items

monitors = fetch_all()
print(f"Total monitors: {len(monitors)}")

# Our stretch: Chertsey (easting ~505000) to Teddington (~517000)
# But CSOs on tributaries (Wey, Mole, Hogsmill, Ember) also affect us
# Let's look at EVERYTHING in our geographic box
MIN_E, MAX_E = 503000, 518000
MIN_N, MAX_N = 155000, 175000

nearby = [m for m in monitors if MIN_E <= (m.get("x") or 0) <= MAX_E and MIN_N <= (m.get("y") or 0) <= MAX_N]
nearby.sort(key=lambda m: m.get("x", 0) or 0)

print(f"\nAll monitors in geographic box: {len(nearby)}")
print(f"\n{'Name':<50} {'Watercourse':<35} {'E':>7} {'N':>7} {'Status':<18} {'48h'}")
print("-" * 145)
for m in nearby:
    print(f"{(m.get('locationName','')[:49]):<50} "
          f"{(m.get('receivingWaterCourse','')[:34]):<35} "
          f"{m.get('x',''):>7} "
          f"{m.get('y',''):>7} "
          f"{(m.get('alertStatus','')):<18} "
          f"{m.get('alertPast48Hours','')}")

# Group by watercourse
from collections import Counter
wc_counts = Counter(m.get("receivingWaterCourse", "Unknown") for m in nearby)
print(f"\n\nWatercourse breakdown:")
for wc, count in wc_counts.most_common():
    print(f"  {count:>3}x {wc}")
