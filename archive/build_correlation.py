#!/usr/bin/env python3
"""Build correlation dataset: pair ThamesWatch EC readings with rainfall and river level."""

import csv
import json
from datetime import datetime, timedelta
from collections import defaultdict

# ── Load rainfall data ──
def load_rainfall(path, name):
    """Load daily rainfall CSV into {date_str: mm} dict."""
    rain = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                date = row['date']
                val = float(row['value'])
                rain[date] = val
            except (ValueError, KeyError):
                continue
    print(f"  {name}: {len(rain)} days loaded ({min(rain.keys()) if rain else '?'} to {max(rain.keys()) if rain else '?'})")
    return rain

# ── Load Teddington level (15-min) → daily mean ──
def load_daily_level(path):
    """Aggregate 15-min level readings to daily mean."""
    daily = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                date = row['date']
                val = float(row['value'])
                daily[date].append(val)
            except (ValueError, KeyError):
                continue
    result = {d: sum(v)/len(v) for d, v in daily.items()}
    print(f"  Teddington level: {len(result)} days ({min(result.keys()) if result else '?'} to {max(result.keys()) if result else '?'})")
    return result

# ── Calculate derived rainfall metrics ──
def calc_rain_metrics(rain_data, test_date_str):
    """Calculate rainfall metrics for a given test date."""
    test_date = datetime.strptime(test_date_str, '%Y-%m-%d')

    # Rain in prior 24h, 48h, 72h, 7 days
    rain_24h = 0
    rain_48h = 0
    rain_72h = 0
    rain_7d = 0

    # Days since last significant rain (>2mm)
    dry_days = None

    for i in range(1, 8):  # 1-7 days back
        d = (test_date - timedelta(days=i)).strftime('%Y-%m-%d')
        r = rain_data.get(d, 0)

        if i <= 1: rain_24h += r
        if i <= 2: rain_48h += r
        if i <= 3: rain_72h += r
        rain_7d += r

        if dry_days is None and r > 2.0:
            dry_days = i - 1  # days of dry weather before this rain

    # Extend dry days search to 14 days if not found in 7
    if dry_days is None:
        for i in range(8, 15):
            d = (test_date - timedelta(days=i)).strftime('%Y-%m-%d')
            r = rain_data.get(d, 0)
            if r > 2.0:
                dry_days = i - 1
                break

    if dry_days is None:
        dry_days = 14  # cap at 14

    # Max single-day rainfall in prior 3 days
    max_rain_3d = 0
    for i in range(1, 4):
        d = (test_date - timedelta(days=i)).strftime('%Y-%m-%d')
        r = rain_data.get(d, 0)
        max_rain_3d = max(max_rain_3d, r)

    return {
        'rain_24h': round(rain_24h, 2),
        'rain_48h': round(rain_48h, 2),
        'rain_72h': round(rain_72h, 2),
        'rain_7d': round(rain_7d, 2),
        'dry_days': dry_days,
        'max_rain_3d': round(max_rain_3d, 2),
    }

# ── ThamesWatch test data (manually entered from API results) ──
# Focus on the two richest sites: Walton Wharf (102 results) and Kingston Albany Reach (56 results)
# Plus Ditton's Bend (17 results with recent winter data)

test_data = []

# Walton Wharf - all results
walton_wharf = [
    ('2024-05-21', 780, 68), ('2024-05-27', 250, 71), ('2024-06-04', 430, 154),
    ('2024-06-10', 340, 90), ('2024-06-13', 200, 78), ('2024-06-17', 420, 114),
    ('2024-06-20', 140, 760), ('2024-06-24', 480, 92), ('2024-06-27', 400, 87),
    ('2024-07-01', 150, 56), ('2024-07-04', 280, 68), ('2024-07-08', 4300, 400),
    ('2024-07-09', 510, 102), ('2024-07-10', 500, 440), ('2024-07-11', 480, 440),
    ('2024-07-15', 390, 107), ('2024-07-18', 870, 148), ('2024-07-22', 2100, 92),
    ('2024-07-25', 240, 103), ('2024-07-29', 370, 86), ('2024-08-01', 270, 38),
    ('2024-08-05', 280, 92), ('2024-08-08', 320, None), ('2024-08-15', 220, 68),
    ('2024-08-19', 280, 76), ('2024-08-27', 2400, 250), ('2024-08-29', 230, 57),
    ('2024-09-02', 2300, 290), ('2024-09-06', 3100, 820), ('2024-09-09', 1700, 470),
    ('2024-09-12', 430, 152), ('2024-09-17', 380, 60), ('2024-09-20', 790, 110),
    ('2024-09-23', 7100, 2000), ('2024-09-25', 3300, None), ('2024-10-01', 1100, 440),
    ('2024-10-15', 4200, 640), ('2024-10-22', 3600, 610), ('2024-10-28', 470, 91),
    ('2024-11-12', 2600, 99), ('2024-11-20', 2200, 1020), ('2024-11-27', 3000, 1080),
    ('2024-12-31', 410, 0), ('2025-01-14', 1400, 510), ('2025-02-05', 840, 320),
    ('2025-02-11', 2300, 450), ('2025-02-14', 1033, 0), ('2025-02-19', 420, 340),
    ('2025-02-27', 4800, 990), ('2025-03-05', 500, 92), ('2025-03-19', 350, 90),
    ('2025-04-01', 270, 39), ('2025-04-08', 600, 49), ('2025-04-16', 330, None),
    ('2025-04-22', 130, None), ('2025-04-29', 100, None), ('2025-05-03', 1200, None),
    ('2025-05-08', 100, None), ('2025-05-15', 130, None), ('2025-05-20', 100, None),
    ('2025-05-27', 47, 34), ('2025-06-03', 78, 26), ('2025-06-05', 300, None),
    ('2025-06-12', 340, 61), ('2025-06-26', 120, 47), ('2025-07-03', 35, None),
    ('2025-07-10', 500, 102), ('2025-07-17', 590, 39), ('2025-07-24', 270, 170),
    ('2025-07-31', 260, 63), ('2025-08-07', 100, None), ('2025-08-14', 400, None),
    ('2025-08-21', 170, 81), ('2025-08-27', 62, 101), ('2025-09-03', 10000, None),
    ('2025-09-15', 1700, None), ('2025-09-16', 1100, None), ('2025-09-18', 360, 110),
    ('2025-09-25', 310, 112), ('2025-10-07', 300, None), ('2025-10-14', 650, None),
    ('2025-10-16', 900, None), ('2025-10-21', 3500, None), ('2025-10-28', 850, None),
    ('2025-11-04', 650, None), ('2025-11-11', 530, None), ('2025-11-18', 1600, 95),
    ('2025-11-25', 1430, None), ('2025-12-05', 1300, None), ('2025-12-10', 1660, None),
    ('2025-12-16', 300, None), ('2025-12-19', 5400, None), ('2026-01-08', 800, None),
    ('2026-01-15', 3100, None), ('2026-01-23', 3700, None), ('2026-03-05', 400, None),
    ('2026-03-12', 300, None),
]
for date, ec, ei in walton_wharf:
    test_data.append({'site': 'Walton Wharf', 'date': date, 'ec': ec, 'ei': ei})

# Kingston Albany Reach - key results
kingston = [
    ('2024-04-15', 460, 120), ('2024-04-15', 1300, 350), ('2024-04-30', 1900, 300),
    ('2024-05-08', 1300, 700), ('2024-05-10', 450, 79), ('2024-05-13', 300, 87),
    ('2024-05-17', 520, 71), ('2024-05-21', 140, 25), ('2024-05-24', 2000, 114),
    ('2024-05-28', 2400, 160), ('2024-05-30', 240, 102), ('2024-06-03', 430, 64),
    ('2024-06-06', 380, 106), ('2024-06-12', 180, 62), ('2024-06-13', 720, 123),
    ('2024-06-17', 260, 51), ('2024-06-20', 1600, 230), ('2024-06-24', 160, 34),
    ('2024-06-27', 280, 95), ('2024-07-01', 110, 2), ('2024-07-04', 550, 142),
    ('2024-07-09', 910, None), ('2024-07-11', 1400, 410), ('2024-07-15', 290, 54),
    ('2024-07-18', 3900, 430), ('2024-07-22', 200, 28), ('2024-07-25', 560, 156),
    ('2024-07-31', 230, 65), ('2024-08-05', 150, 40), ('2024-08-06', 1200, 124),
    ('2024-08-14', 2900, 430), ('2024-08-16', 2500, 540), ('2024-08-23', 950, 530),
    ('2024-08-27', 850, 150), ('2024-08-30', 1300, 127), ('2024-09-07', 4100, 1550),
    ('2025-04-11', 210, 124), ('2025-05-13', 37, 4), ('2025-05-22', 100, 100),
    ('2025-05-30', 8, 6), ('2025-06-09', 430, 64), ('2025-06-11', 100, 39),
    ('2025-07-09', 83, 19), ('2025-07-24', 100, 43), ('2025-08-07', 100, 63),
    ('2025-08-15', 100, 100),
]
for date, ec, ei in kingston:
    test_data.append({'site': 'Kingston Albany Reach', 'date': date, 'ec': ec, 'ei': ei})

# Ditton's Bend - recent winter data
dittons = [
    ('2025-10-16', 300, None), ('2025-10-22', 1100, None), ('2025-10-30', 766, None),
    ('2025-11-07', 200, None), ('2025-11-14', 700, None), ('2025-11-20', 1000, None),
    ('2025-11-28', 500, None), ('2025-12-05', 4300, None), ('2025-12-10', 2130, None),
    ('2025-12-19', 12530, None), ('2025-12-26', 970, None), ('2026-01-06', 770, None),
    ('2026-01-14', 3200, None), ('2026-01-29', 2430, None), ('2026-02-19', 2930, None),
    ('2026-02-26', 530, None), ('2026-03-13', 330, None),
]
for date, ec, ei in dittons:
    test_data.append({'site': "Ditton's Bend", 'date': date, 'ec': ec, 'ei': ei})

# Chertsey
chertsey = [
    ('2024-06-10', 460, 98), ('2024-06-27', 73, 49), ('2024-07-02', 92, 35),
    ('2024-07-08', 6200, 520), ('2024-07-10', 2300, 200), ('2024-07-12', 170, 67),
    ('2024-07-24', 140, 46), ('2024-09-06', 700, 570), ('2024-09-18', 120, 41),
    ('2025-12-15', 500, None), ('2025-12-19', 2600, None), ('2026-01-14', 3000, None),
]
for date, ec, ei in chertsey:
    test_data.append({'site': 'Chertsey', 'date': date, 'ec': ec, 'ei': ei})

# Teddington Hawker Centre
teddington = [
    ('2024-03-19', 910, 110), ('2024-05-20', 190, 25), ('2024-06-24', 67, 37),
    ('2024-07-08', 250, 90), ('2024-07-17', 1700, 210), ('2024-08-19', 200, 86),
    ('2025-07-02', 190, 10), ('2025-07-10', 1000, 130), ('2025-07-16', 1000, 10),
    ('2025-07-20', 1000, 1000), ('2025-08-07', 530, 160),
]
for date, ec, ei in teddington:
    test_data.append({'site': 'Teddington', 'date': date, 'ec': ec, 'ei': ei})

# Kingston Half Mile Tree
kingston_hmt = [
    ('2024-04-15', 650, 120), ('2024-04-30', 1100, 410), ('2024-05-13', 390, 64),
    ('2024-05-21', 93, 22), ('2024-05-28', 500, 170), ('2024-06-03', 160, 54),
    ('2024-06-12', 300, 61), ('2024-06-17', 240, 31), ('2024-06-24', 210, 32),
    ('2024-07-01', 220, 50), ('2024-07-09', 480, None), ('2024-07-15', 180, 39),
    ('2024-07-22', 170, 23), ('2024-08-05', 88, 25), ('2024-08-27', 360, 180),
    ('2025-05-13', 52, 5), ('2025-05-22', 68, 25), ('2025-05-30', 9, 1),
    ('2025-06-11', 100, 34), ('2025-07-09', 31, 11), ('2025-07-16', 460, 79),
    ('2025-07-24', 100, 6), ('2025-08-07', 100, 48), ('2025-08-15', 100, 72),
]
for date, ec, ei in kingston_hmt:
    test_data.append({'site': 'Kingston HMT', 'date': date, 'ec': ec, 'ei': ei})

print(f"\nTotal test results: {len(test_data)}")

# ── Load environmental data ──
print("\nLoading environmental data...")
hogsmill_rain = load_rainfall('/tmp/hogsmill_rain.csv', 'Hogsmill rain')
chertsey_rain = load_rainfall('/tmp/chertsey_rain.csv', 'Chertsey rain')
teddington_level = load_daily_level('/tmp/teddington_level.csv')

# Use Hogsmill as primary (covers full date range), Chertsey as secondary
primary_rain = hogsmill_rain

# ── Build correlation dataset ──
print("\nBuilding correlation dataset...")
results = []
matched = 0
unmatched = 0

for t in test_data:
    date = t['date']
    metrics = calc_rain_metrics(primary_rain, date)
    level = teddington_level.get(date)

    if metrics['rain_7d'] is not None:
        matched += 1
    else:
        unmatched += 1

    # Determine season
    month = int(date.split('-')[1])
    if month in [12, 1, 2]: season = 'winter'
    elif month in [3, 4, 5]: season = 'spring'
    elif month in [6, 7, 8]: season = 'summer'
    else: season = 'autumn'

    row = {
        'site': t['site'],
        'date': date,
        'ec': t['ec'],
        'ei': t['ei'],
        'season': season,
        'rain_24h': metrics['rain_24h'],
        'rain_48h': metrics['rain_48h'],
        'rain_72h': metrics['rain_72h'],
        'rain_7d': metrics['rain_7d'],
        'dry_days': metrics['dry_days'],
        'max_rain_3d': metrics['max_rain_3d'],
        'teddington_level': round(level, 3) if level else None,
    }
    results.append(row)

print(f"Matched: {matched}, Unmatched rain data: {unmatched}")

# ── Write CSV ──
output_path = '/tmp/thameswatch_correlation.csv'
fields = ['site', 'date', 'ec', 'ei', 'season', 'rain_24h', 'rain_48h', 'rain_72h', 'rain_7d', 'dry_days', 'max_rain_3d', 'teddington_level']
with open(output_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(results)

print(f"\nDataset written to {output_path}")
print(f"Total rows: {len(results)}")

# ── Quick analysis ──
print("\n" + "="*70)
print("QUICK ANALYSIS")
print("="*70)

# Split into low-rain and high-rain groups
low_rain = [r for r in results if r['rain_48h'] <= 2 and r['ec'] is not None]
med_rain = [r for r in results if 2 < r['rain_48h'] <= 10 and r['ec'] is not None]
high_rain = [r for r in results if r['rain_48h'] > 10 and r['ec'] is not None]

def stats(group, label):
    if not group:
        print(f"\n{label}: no data")
        return
    ecs = [r['ec'] for r in group]
    avg = sum(ecs) / len(ecs)
    median = sorted(ecs)[len(ecs)//2]
    under500 = sum(1 for e in ecs if e <= 500)
    under1000 = sum(1 for e in ecs if e <= 1000)
    over2000 = sum(1 for e in ecs if e > 2000)
    print(f"\n{label} (n={len(group)}):")
    print(f"  EC mean: {avg:.0f}  median: {median}  min: {min(ecs)}  max: {max(ecs)}")
    print(f"  EC ≤500 (good): {under500}/{len(group)} ({100*under500/len(group):.0f}%)")
    print(f"  EC ≤1000 (ok):  {under1000}/{len(group)} ({100*under1000/len(group):.0f}%)")
    print(f"  EC >2000 (bad): {over2000}/{len(group)} ({100*over2000/len(group):.0f}%)")

stats(low_rain, "LOW RAIN (≤2mm in 48h)")
stats(med_rain, "MODERATE RAIN (2-10mm in 48h)")
stats(high_rain, "HEAVY RAIN (>10mm in 48h)")

# Dry days analysis
print("\n" + "-"*50)
print("BY DRY DAYS (days since >2mm rain):")
for d in [0, 1, 2, 3, 4, 5]:
    group = [r for r in results if r['dry_days'] == d and r['ec'] is not None]
    if group:
        ecs = [r['ec'] for r in group]
        avg = sum(ecs) / len(ecs)
        under500 = sum(1 for e in ecs if e <= 500)
        print(f"  {d} dry days: n={len(group):3d}  mean EC={avg:6.0f}  ≤500: {under500}/{len(group)} ({100*under500/len(group):.0f}%)")

long_dry = [r for r in results if r['dry_days'] >= 6 and r['ec'] is not None]
if long_dry:
    ecs = [r['ec'] for r in long_dry]
    avg = sum(ecs) / len(ecs)
    under500 = sum(1 for e in ecs if e <= 500)
    print(f"  6+ dry days: n={len(long_dry):3d}  mean EC={avg:6.0f}  ≤500: {under500}/{len(long_dry)} ({100*under500/len(long_dry):.0f}%)")

# Season analysis
print("\n" + "-"*50)
print("BY SEASON:")
for s in ['spring', 'summer', 'autumn', 'winter']:
    group = [r for r in results if r['season'] == s and r['ec'] is not None]
    if group:
        ecs = [r['ec'] for r in group]
        avg = sum(ecs) / len(ecs)
        under500 = sum(1 for e in ecs if e <= 500)
        print(f"  {s:8s}: n={len(group):3d}  mean EC={avg:6.0f}  ≤500: {under500}/{len(group)} ({100*under500/len(group):.0f}%)")

# The key scenario: "tested 5 days ago, showed high, hasn't rained"
print("\n" + "-"*50)
print("KEY SCENARIO: After high readings + dry weather")
print("Looking for readings that follow a previous high reading at same site with dry weather between:")
# Group by site, look for pairs where prior reading was high and current is after dry spell
by_site = defaultdict(list)
for r in sorted(results, key=lambda x: x['date']):
    by_site[r['site']].append(r)

recovery_cases = []
for site, readings in by_site.items():
    for i in range(1, len(readings)):
        prev = readings[i-1]
        curr = readings[i]
        if prev['ec'] and prev['ec'] > 1000 and curr['ec']:
            days_between = (datetime.strptime(curr['date'], '%Y-%m-%d') - datetime.strptime(prev['date'], '%Y-%m-%d')).days
            if days_between <= 14 and curr['dry_days'] >= 3:
                recovery_cases.append({
                    'site': site,
                    'prev_date': prev['date'],
                    'prev_ec': prev['ec'],
                    'curr_date': curr['date'],
                    'curr_ec': curr['ec'],
                    'days_between': days_between,
                    'dry_days': curr['dry_days'],
                    'rain_48h': curr['rain_48h'],
                })

if recovery_cases:
    print(f"\nFound {len(recovery_cases)} recovery cases (prior EC>1000, current has 3+ dry days):")
    for c in recovery_cases:
        arrow = "↓" if c['curr_ec'] < c['prev_ec'] else "↑"
        status = "RECOVERED" if c['curr_ec'] <= 500 else "STILL HIGH"
        print(f"  {c['site']:25s} {c['prev_date']} EC={c['prev_ec']:5d} → {c['curr_date']} EC={c['curr_ec']:5d} {arrow} ({c['days_between']}d gap, {c['dry_days']}d dry) [{status}]")

    recovered = sum(1 for c in recovery_cases if c['curr_ec'] <= 500)
    print(f"\n  Recovery rate (EC drops to ≤500): {recovered}/{len(recovery_cases)} ({100*recovered/len(recovery_cases):.0f}%)")
