"""Environment Agency Hydrology API client — river flow and rainfall.

Public API at environment.data.gov.uk/hydrology, no authentication.

Two cadences per gauge: a daily series (id contains '-86400-') and a 15-minute
series ('-900-'). Flow uses the daily mean (lags ~2 days). Rainfall uses the 15-minute
series aggregated to daily totals so predictions run on current rain, not stale data —
the rainfall 15-minute series here updates within ~1 hour.

NOTE: the Hydrology 15-minute *flow* series is unreliable for live use (it froze
~2026-04-15 for our gauges). Live 15-minute flow for surge detection comes from the
flood-monitoring API instead — see tw.flood_monitoring.
"""

import csv
import os
import time
from datetime import datetime, timedelta

import requests

from tw.config import EA_HYDROLOGY_ROOT, EA_STATIONS

# Value column header per station kind — preserves the existing CSV formats.
_VALUE_HEADER = {"flow": "flow_m3s", "rainfall": "rainfall_mm"}


def _get(url, params, timeout=60, max_retries=4):
    """GET with polite backoff — the EA Hydrology API rate-limits (HTTP 429)."""
    delay = 3
    for attempt in range(max_retries):
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code in (429, 503) and attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def fetch_readings(measure_id, limit=5000, since=None):
    """Return {date_str: value} for a daily measure.

    `since` (ISO date) filters server-side to readings on/after that date.
    """
    params = {"_limit": limit, "_sort": "-dateTime"}
    if since:
        params["mineq-date"] = since
    url = f"{EA_HYDROLOGY_ROOT}/id/measures/{measure_id}/readings.json"
    r = _get(url, params)
    out = {}
    for item in r.json().get("items", []):
        d = (item.get("dateTime") or "")[:10]
        v = item.get("value")
        if d and v is not None:
            out[d] = float(v)
    return out


def fetch_station_readings(station_key, since=None):
    """Config-aware fetch — look up the EAStation and fetch its daily measure."""
    station = EA_STATIONS[station_key]
    if not station.measure_id:
        raise ValueError(f"station '{station_key}' has no measure_id — rediscover it first")
    return fetch_readings(station.measure_id, since=since)


def fetch_rainfall_15min_daily(measure_id, since=None, limit=5000):
    """Fetch the 15-minute rainfall series and aggregate it to daily totals.

    The 15-minute series updates within ~1 hour — unlike the daily series, which
    lags 1-3 days. Returns {date_str: mm}. The most recent day is a running total
    (partial — it firms up as the day progresses and on the next fetch).
    """
    m15 = measure_id.replace("-86400-", "-900-")
    params = {"_limit": limit, "_sort": "-dateTime"}
    if since:
        params["mineq-date"] = since
    url = f"{EA_HYDROLOGY_ROOT}/id/measures/{m15}/readings.json"
    r = _get(url, params)
    daily = {}
    for item in r.json().get("items", []):
        d = (item.get("dateTime") or "")[:10]
        v = item.get("value")
        if d and v is not None:
            daily[d] = daily.get(d, 0.0) + float(v)
    return {d: round(v, 2) for d, v in daily.items()}


# Live 15-minute flow + surge detection moved to tw.flood_monitoring — the Hydrology
# 15-minute flow series proved unreliable for live use (frozen ~2026-04-15 for our
# gauges). See that module for fetch_15min_flow / recent_flow_surge.


def search_stations(search=None, observed_property=None, lat=None, long=None,
                    dist=None, limit=20):
    """Search the EA station catalogue — used to rediscover missing station GUIDs."""
    params = {"_limit": limit}
    if search:
        params["search"] = search
    if observed_property:
        params["observedProperty"] = observed_property
    if lat is not None:
        params["lat"] = lat
    if long is not None:
        params["long"] = long
    if dist is not None:
        params["dist"] = dist
    r = _get(f"{EA_HYDROLOGY_ROOT}/id/stations.json", params, timeout=40)
    return r.json().get("items", [])


def list_daily_measures(station_guid):
    """Return the daily (-86400-) measures for a station — id + label."""
    r = _get(f"{EA_HYDROLOGY_ROOT}/id/stations/{station_guid}/measures.json", {}, timeout=40)
    out = []
    for m in r.json().get("items", []):
        mid = m.get("@id", "").split("/")[-1]
        if "-86400-" in mid:
            out.append({"measure_id": mid, "label": m.get("label", "")})
    return out


def _read_csv_dates(csv_path):
    """Return {date: value_str} from an existing 2-column data CSV."""
    rows = {}
    with open(csv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("date"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                rows[parts[0]] = parts[1]
    return rows


def topup_csv(station_key, csv_path):
    """Incrementally update a station's daily CSV with the latest readings.

    Rainfall uses the 15-minute series aggregated to daily totals and re-fetches a
    trailing window so recently-partial days firm up. Flow uses the daily-mean
    series. Returns the number of rows added or changed.
    """
    station = EA_STATIONS[station_key]
    header = _VALUE_HEADER[station.kind]

    existing = _read_csv_dates(csv_path) if os.path.exists(csv_path) else {}
    last_date = max(existing) if existing else None

    if station.kind == "rainfall":
        # Re-fetch from 5 days before the CSV's last date — recent days may have
        # been partial when last written; the 15-minute series firms them up.
        since = None
        if last_date:
            since = (datetime.strptime(last_date, "%Y-%m-%d")
                     - timedelta(days=5)).strftime("%Y-%m-%d")
        fetched = fetch_rainfall_15min_daily(station.measure_id, since=since)
    else:
        fetched = fetch_station_readings(station_key, since=last_date)

    changed = [d for d, v in fetched.items()
               if d not in existing or float(existing[d]) != v]
    if not changed:
        return 0

    merged = dict(existing)
    merged.update(fetched)   # fetched values overwrite — rain days firm up over time

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", header])
        for d in sorted(merged):
            writer.writerow([d, merged[d]])
    return len(changed)
