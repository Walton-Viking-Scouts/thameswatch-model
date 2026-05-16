#!/usr/bin/env python3
"""Fetch discharge history for CSO monitors near our Thames stretch and build correlation data."""

import requests
import json
import csv
from datetime import datetime, timedelta

API_ROOT = "https://api.thameswater.co.uk"
ALERTS_ENDPOINT = "/opendata/v2/discharge/alerts"
API_LIMIT = 1000

# Our 14 monitors from the geographic search
MONITOR_NAMES = [
    "Woking",
    "Ripley",
    "Dartnell Park, Byfleet",
    "Weybridge",
    "Cobham Bridge, Adj Cobham PS",
    "Stoke Road, Cobham",
    "Esher",
    "Commonside",
    "Leatherhead",
    "River Lane",
    "Amyand Park Road, Twickenham",
    "Old Palace Lane",
    "Portsmouth Road, Uxbridge Road",
    "Kingston Main",
]

def fetch_monitor_history(location_name):
    """Fetch all discharge alerts for a given monitor."""
    url = API_ROOT + ALERTS_ENDPOINT
    all_items = []
    offset = 0

    while True:
        params = {
            "limit": API_LIMIT,
            "offset": offset,
            "locationName": location_name,
        }
        r = requests.get(url, params=params)

        if r.status_code != 200:
            print(f"  Error {r.status_code} for {location_name}")
            break

        data = r.json()
        if "items" not in data or not data["items"]:
            break

        items = data["items"]
        all_items.extend(items)

        if len(items) < API_LIMIT:
            break
        offset += API_LIMIT

    return all_items


def parse_datetime(dt_str):
    """Parse ISO datetime string to datetime object."""
    if not dt_str:
        return None
    # Handle various formats
    for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    # Try with timezone offset
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except:
        return None


def build_discharge_periods(alerts):
    """Convert alert state-changes into discharge periods (start, stop) tuples."""
    # Sort by datetime
    alerts.sort(key=lambda a: a.get("dateTime", "") or a.get("datetime", ""))

    periods = []
    current_start = None

    for alert in alerts:
        alert_type = alert.get("alertType", "") or alert.get("alerttype", "")
        dt_str = alert.get("dateTime", "") or alert.get("datetime", "")
        dt = parse_datetime(dt_str)

        if not dt:
            continue

        if "start" in alert_type.lower() or "discharge" in alert_type.lower():
            current_start = dt
        elif "stop" in alert_type.lower() or "no discharge" in alert_type.lower():
            if current_start:
                periods.append((current_start, dt))
                current_start = None

    # If still discharging, mark as ongoing
    if current_start:
        periods.append((current_start, datetime.now()))

    return periods


def was_cso_active(discharge_periods_by_monitor, check_date, hours_window=48):
    """Check if any CSO was active within hours_window before check_date."""
    window_start = check_date - timedelta(hours=hours_window)

    for monitor_name, periods in discharge_periods_by_monitor.items():
        for start, stop in periods:
            # Discharge overlaps with our window if it started before window end
            # and stopped after window start
            if start <= check_date and stop >= window_start:
                return True, monitor_name
    return False, None


def count_cso_hours(discharge_periods_by_monitor, check_date, hours_window=48):
    """Count total CSO discharge hours within window before check_date."""
    window_start = check_date - timedelta(hours=hours_window)
    total_hours = 0
    active_monitors = []

    for monitor_name, periods in discharge_periods_by_monitor.items():
        monitor_hours = 0
        for start, stop in periods:
            # Calculate overlap with window
            overlap_start = max(start, window_start)
            overlap_stop = min(stop, check_date)
            if overlap_start < overlap_stop:
                hours = (overlap_stop - overlap_start).total_seconds() / 3600
                monitor_hours += hours

        if monitor_hours > 0:
            total_hours += monitor_hours
            active_monitors.append((monitor_name, round(monitor_hours, 1)))

    return round(total_hours, 1), active_monitors


def main():
    print("=== Fetching discharge history for 14 nearby monitors ===\n")

    all_discharge_periods = {}
    all_alerts_raw = {}

    for name in MONITOR_NAMES:
        print(f"Fetching: {name}...", end=" ")
        alerts = fetch_monitor_history(name)
        print(f"{len(alerts)} alerts")

        all_alerts_raw[name] = alerts
        periods = build_discharge_periods(alerts)
        all_discharge_periods[name] = periods

        # Summary
        if periods:
            total_hours = sum((stop - start).total_seconds() / 3600 for start, stop in periods)
            print(f"  → {len(periods)} discharge events, {total_hours:.0f} total hours")

    # Save raw alerts
    with open("thameswatch-analysis/cso_alerts_raw.json", "w") as f:
        json.dump(all_alerts_raw, f, indent=2, default=str)
    print(f"\nSaved raw alerts to cso_alerts_raw.json")

    # Save discharge periods summary
    summary = {}
    for name, periods in all_discharge_periods.items():
        summary[name] = {
            "total_events": len(periods),
            "total_hours": round(sum((s - e).total_seconds() / 3600 for e, s in []) if not periods else sum((stop - start).total_seconds() / 3600 for start, stop in periods), 1),
            "events": [{"start": str(s), "stop": str(e)} for s, e in periods]
        }
    with open("thameswatch-analysis/cso_discharge_periods.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("Saved discharge periods to cso_discharge_periods.json")

    # Now cross-reference with ThamesWatch correlation data
    print("\n=== Cross-referencing with ThamesWatch test results ===\n")

    # Read existing correlation CSV
    with open("thameswatch-analysis/thameswatch_correlation.csv", "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    print(f"Loaded {len(rows)} test results from correlation dataset")

    # Add CSO columns
    new_fieldnames = fieldnames + ["cso_active_48h", "cso_hours_48h", "cso_active_monitors", "cso_active_72h", "cso_hours_72h"]

    enriched = 0
    cso_positive_48 = 0
    cso_positive_72 = 0

    for row in rows:
        # Parse the test date
        date_str = row.get("date") or row.get("Date") or row.get("test_date")
        if not date_str:
            row["cso_active_48h"] = ""
            row["cso_hours_48h"] = ""
            row["cso_active_monitors"] = ""
            row["cso_active_72h"] = ""
            row["cso_hours_72h"] = ""
            continue

        test_date = parse_datetime(date_str)
        if not test_date:
            # Try simpler date format
            try:
                test_date = datetime.strptime(date_str, "%Y-%m-%d")
                test_date = test_date.replace(hour=12)  # Assume midday
            except:
                row["cso_active_48h"] = ""
                row["cso_hours_48h"] = ""
                row["cso_active_monitors"] = ""
                row["cso_active_72h"] = ""
                row["cso_hours_72h"] = ""
                continue

        # Check 48h window
        active_48, monitor_48 = was_cso_active(all_discharge_periods, test_date, 48)
        hours_48, monitors_48 = count_cso_hours(all_discharge_periods, test_date, 48)

        # Check 72h window
        active_72, _ = was_cso_active(all_discharge_periods, test_date, 72)
        hours_72, _ = count_cso_hours(all_discharge_periods, test_date, 72)

        row["cso_active_48h"] = str(active_48)
        row["cso_hours_48h"] = str(hours_48)
        row["cso_active_monitors"] = "; ".join(f"{name}({hrs}h)" for name, hrs in monitors_48) if monitors_48 else ""
        row["cso_active_72h"] = str(active_72)
        row["cso_hours_72h"] = str(hours_72)

        enriched += 1
        if active_48:
            cso_positive_48 += 1
        if active_72:
            cso_positive_72 += 1

    print(f"Enriched {enriched} rows")
    print(f"CSO active within 48h: {cso_positive_48}/{enriched} ({100*cso_positive_48/enriched:.0f}%)")
    print(f"CSO active within 72h: {cso_positive_72}/{enriched} ({100*cso_positive_72/enriched:.0f}%)")

    # Save enriched CSV
    output_path = "thameswatch-analysis/thameswatch_correlation_with_cso.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved enriched dataset to {output_path}")

    # Quick analysis: does CSO improve prediction?
    print("\n=== Quick CSO Impact Analysis ===\n")

    ec_field = None
    for candidate in ["ec", "EC", "e_coli", "ecoli", "EC_cfu_100ml"]:
        if candidate in fieldnames:
            ec_field = candidate
            break

    if ec_field:
        cso_yes = [row for row in rows if row["cso_active_48h"] == "True" and row[ec_field]]
        cso_no = [row for row in rows if row["cso_active_48h"] == "False" and row[ec_field]]

        if cso_yes and cso_no:
            def safe_vals(rows, field):
                vals = []
                for r in rows:
                    try:
                        vals.append(float(r[field]))
                    except (ValueError, TypeError):
                        pass
                return vals

            ec_with_cso = safe_vals(cso_yes, ec_field)
            ec_without_cso = safe_vals(cso_no, ec_field)

            if ec_with_cso and ec_without_cso:
                avg_with = sum(ec_with_cso) / len(ec_with_cso)
                avg_without = sum(ec_without_cso) / len(ec_without_cso)
                safe_with = sum(1 for v in ec_with_cso if v <= 500) / len(ec_with_cso) * 100
                safe_without = sum(1 for v in ec_without_cso if v <= 500) / len(ec_without_cso) * 100

                print(f"EC field: {ec_field}")
                print(f"  CSO active (48h):   n={len(ec_with_cso):>3}, mean EC={avg_with:>8.0f}, safe(≤500)={safe_with:.0f}%")
                print(f"  No CSO (48h):       n={len(ec_without_cso):>3}, mean EC={avg_without:>8.0f}, safe(≤500)={safe_without:.0f}%")
                print(f"  Ratio: {avg_with/avg_without:.1f}x higher EC when CSO active")
    else:
        print(f"Could not find EC column. Available: {fieldnames}")
        print("Manual analysis needed on the enriched CSV.")


if __name__ == "__main__":
    main()
