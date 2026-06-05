"""Thames Water EDM API client — storm-overflow (CSO) discharge data.

Public API at api.thameswater.co.uk/opendata/v2, no authentication. Two endpoints:
  /discharge/alerts  — historical start/stop alerts per monitor
  /discharge/status  — current status of every monitor (alertStatus, alertPast48Hours)
"""

import time
from datetime import datetime, timedelta

import requests

from tw.config import THAMES_WATER_ROOT, CSO_MONITOR_NAMES

ALERTS_ENDPOINT = f"{THAMES_WATER_ROOT}/opendata/v2/discharge/alerts"
STATUS_ENDPOINT = f"{THAMES_WATER_ROOT}/opendata/v2/discharge/status"
API_LIMIT = 1000


def _get(url, params, timeout=30, max_retries=4):
    """GET with backoff on rate-limiting (HTTP 429/503).

    The EDM API throttles when many monitors are fetched in quick succession (predict +
    build_recent both sweep every monitor). Without this a throttled request returned a
    non-200 that callers read as "no data" — silently dropping a monitor's discharge
    history (e.g. a panel showing an overflow as quiet when it had discharged for hours).
    """
    delay = 3
    for attempt in range(max_retries):
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code in (429, 503) and attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        return r
    return r


# --- datetime parsing --------------------------------------------------------

def parse_datetime(dt_str):
    """Parse an ISO datetime string to a naive datetime, or None."""
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


# --- discharge history -------------------------------------------------------

def fetch_monitor_history(location_name):
    """Fetch all discharge alerts for a single monitor, handling pagination."""
    all_items = []
    offset = 0
    while True:
        r = _get(ALERTS_ENDPOINT,
                 {"limit": API_LIMIT, "offset": offset, "locationName": location_name})
        if r.status_code != 200:
            break
        items = r.json().get("items", [])
        if not items:
            break
        all_items.extend(items)
        if len(items) < API_LIMIT:
            break
        offset += API_LIMIT
    return all_items


def build_discharge_periods(alerts, now=None):
    """Convert alert start/stop events into (start, stop) datetime tuples.

    An unterminated discharge is closed at `now` (default datetime.now()). For
    back-dated analysis, pass the assessment date so hours are not over-counted.
    """
    if now is None:
        now = datetime.now()
    alerts = sorted(alerts, key=lambda a: a.get("dateTime", "") or a.get("datetime", ""))

    periods = []
    current_start = None
    for alert in alerts:
        alert_type = (alert.get("alertType", "") or alert.get("alerttype", "")).lower()
        dt = parse_datetime(alert.get("dateTime", "") or alert.get("datetime", ""))
        if not dt:
            continue
        if "start" in alert_type or "discharge" in alert_type and "no discharge" not in alert_type:
            current_start = dt
        elif "stop" in alert_type or "no discharge" in alert_type:
            if current_start:
                periods.append((current_start, dt))
                current_start = None
    if current_start:
        periods.append((current_start, now))
    return periods


def fetch_all_discharge_periods(monitor_names=None, now=None):
    """Fetch discharge history for all CSO monitors -> {monitor_name: [(start, stop), ...]}."""
    monitor_names = monitor_names or CSO_MONITOR_NAMES
    return {name: build_discharge_periods(fetch_monitor_history(name), now=now)
            for name in monitor_names}


# --- windowed queries over discharge periods ---------------------------------

def was_cso_active(periods_by_monitor, check_date, hours_window=48):
    """True if any monitor discharged within `hours_window` before check_date."""
    window_start = check_date - timedelta(hours=hours_window)
    for monitor_name, periods in periods_by_monitor.items():
        for start, stop in periods:
            if start <= check_date and stop >= window_start:
                return True, monitor_name
    return False, None


def count_cso_hours(periods_by_monitor, check_date, hours_window=48):
    """Total discharge hours within the window, plus per-monitor active hours."""
    window_start = check_date - timedelta(hours=hours_window)
    total_hours = 0.0
    active_monitors = []
    for monitor_name, periods in periods_by_monitor.items():
        monitor_hours = 0.0
        for start, stop in periods:
            overlap_start = max(start, window_start)
            overlap_stop = min(stop, check_date)
            if overlap_start < overlap_stop:
                monitor_hours += (overlap_stop - overlap_start).total_seconds() / 3600
        if monitor_hours > 0:
            total_hours += monitor_hours
            active_monitors.append((monitor_name, round(monitor_hours, 1)))
    return round(total_hours, 1), active_monitors


# --- current status ----------------------------------------------------------

def fetch_current_status():
    """Fetch current status of every EDM monitor, handling pagination."""
    all_items = []
    offset = 0
    while True:
        r = _get(STATUS_ENDPOINT, {"limit": API_LIMIT, "offset": offset})
        if r.status_code != 200:
            break
        items = r.json().get("items", [])
        if not items:
            break
        all_items.extend(items)
        if len(items) < API_LIMIT:
            break
        offset += API_LIMIT
    return all_items


def _our_monitors(status_items, monitor_names=None):
    """Filter a status list to our CSO monitors (matched by locationName substring)."""
    monitor_names = monitor_names or CSO_MONITOR_NAMES
    return [it for it in status_items
            if any(name in (it.get("locationName") or "") for name in monitor_names)]


def current_active_monitors(status_items=None, monitor_names=None):
    """Our monitors currently discharging right now."""
    if status_items is None:
        status_items = fetch_current_status()
    return [it for it in _our_monitors(status_items, monitor_names)
            if (it.get("alertStatus") or "").lower() not in ("not discharging", "")]


def monitors_active_past_48h(status_items=None, monitor_names=None):
    """Our monitors that discharged in the past 48h, per the API's alertPast48Hours flag."""
    if status_items is None:
        status_items = fetch_current_status()
    return [it for it in _our_monitors(status_items, monitor_names)
            if it.get("alertPast48Hours")]
