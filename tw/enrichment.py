"""Windowed enrichment metrics — pure functions shared by the dataset rebuild and the
live-snapshot assembler. No I/O.
"""

from datetime import datetime, timedelta


def season_of(date_str):
    """Return 'winter'|'spring'|'summer'|'autumn' for an ISO date string."""
    month = int(date_str.split("-")[1])
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer"}.get(month, "autumn")


def calc_rain_metrics(rain_data, test_date_str):
    """Rainfall metrics for a test date from a {date_str: mm} dict.

    Returns rain_24h/48h/72h/7d, dry_days (days since last >2mm rain, capped 14),
    and max_rain_3d. Identical windowing logic to the original build_correlation.py.
    """
    test_date = datetime.strptime(test_date_str, "%Y-%m-%d")
    rain_24h = rain_48h = rain_72h = rain_7d = 0.0
    dry_days = None

    for i in range(1, 8):
        d = (test_date - timedelta(days=i)).strftime("%Y-%m-%d")
        r = rain_data.get(d, 0)
        if i <= 1:
            rain_24h += r
        if i <= 2:
            rain_48h += r
        if i <= 3:
            rain_72h += r
        rain_7d += r
        if dry_days is None and r > 2.0:
            dry_days = i - 1

    if dry_days is None:
        for i in range(8, 15):
            d = (test_date - timedelta(days=i)).strftime("%Y-%m-%d")
            if rain_data.get(d, 0) > 2.0:
                dry_days = i - 1
                break
    if dry_days is None:
        dry_days = 14

    max_rain_3d = max(rain_data.get((test_date - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
                      for i in range(1, 4))

    return {
        "rain_24h": round(rain_24h, 2), "rain_48h": round(rain_48h, 2),
        "rain_72h": round(rain_72h, 2), "rain_7d": round(rain_7d, 2),
        "dry_days": dry_days, "max_rain_3d": round(max_rain_3d, 2),
    }
