"""EA real-time flood-monitoring API client — live 15-minute river flow.

The Hydrology API (tw.ea_hydrology) serves quality-controlled data: its daily mean lags
~2 days, and its 15-minute *flow* series is later still — it froze ~2026-04-15 for our
gauges (rainfall 15-min is unaffected, so that stays on Hydrology). Genuinely live flow
telemetry, current to ~1 hour, is on the separate flood-monitoring API, keyed by station
reference (e.g. "3100TH"). The model uses this only for the tributary-surge signal;
calibration and the absolute flow thresholds stay on the Hydrology daily mean.

Measure ids are not string-buildable — notation varies per station ('-i-15_min-m3_s',
'-water-i-15_min-m3_s', '-Mean-15_min-m3_s') and some stations carry a dead duplicate
with no readings — so they are discovered (discover_flow_measures) and frozen in
tw.config.FLOOD_MONITORING_FLOW.
"""

import time
from datetime import datetime, timedelta

import requests

from tw.config import EA_FLOOD_MONITORING_ROOT, EA_STATIONS, FLOOD_MONITORING_FLOW

# A surge computed from stale telemetry is worse than none (the previous Hydrology path
# silently produced verdicts from weeks-old data). Refuse to compute beyond this age.
MAX_STALENESS_HOURS = 6


class StaleFlowError(RuntimeError):
    """The live 15-minute feed's newest reading is too old to compute a surge from."""


def _get(url, params=None, timeout=30, max_retries=4):
    """GET with polite backoff — the EA APIs rate-limit (HTTP 429)."""
    delay = 3
    for attempt in range(max_retries):
        r = requests.get(url, params=params or {}, timeout=timeout)
        if r.status_code in (429, 503) and attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def _parse(dt):
    """Parse a flood-monitoring ISO dateTime (always UTC 'Z') to a naive UTC datetime."""
    return datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)


def fetch_15min_flow(station_key, hours=55):
    """Recent live 15-minute flow as [(dateTime_str, value), ...], newest first.

    `hours` of history (default 55h) is enough to compare 'now' against a window ~24h
    earlier. Raises if the station has no configured flood-monitoring measure.
    """
    measure = FLOOD_MONITORING_FLOW.get(station_key)
    if not measure:
        raise ValueError(
            f"no flood-monitoring flow measure for station {station_key!r} "
            "(add it to tw.config.FLOOD_MONITORING_FLOW via discover_flow_measures())")
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{EA_FLOOD_MONITORING_ROOT}/id/measures/{measure}/readings"
    r = _get(url, {"since": since, "_sorted": ""})
    out = []
    for item in r.json().get("items", []):
        dt, v = item.get("dateTime"), item.get("value")
        if dt and v is not None:
            out.append((dt, float(v)))
    return out  # _sorted => newest first


def latest_flow(station_key):
    """Most recent live flow reading as (value_m3s, dateTime_str), or (None, None).

    For the status display's per-site flow column. Returns the newest reading regardless
    of age — callers wanting a freshness guarantee should check the timestamp.
    """
    readings = fetch_15min_flow(station_key, hours=6)
    if not readings:
        return None, None
    dt, value = readings[0]
    return value, dt


def recent_flow_surge(station_key, threshold=1.3):
    """Detect a sharp live rise in flow: mean of the last ~2h vs a ~2h window ~24h earlier.

    Same >30% / 24h test the model uses, but on data current to ~1h instead of the
    1-3-day-stale daily series. Returns (rising: bool, recent_m3s, prior_m3s).

    Raises StaleFlowError if the newest live reading is older than MAX_STALENESS_HOURS —
    the guard against the prior bug where a frozen feed silently yielded a surge verdict
    from weeks-old data. Callers (snapshot) treat that as "fall back to the daily signal".
    """
    readings = fetch_15min_flow(station_key)
    if len(readings) < 20:
        return False, None, None

    newest = _parse(readings[0][0])
    age_h = (datetime.utcnow() - newest).total_seconds() / 3600
    if age_h > MAX_STALENESS_HOURS:
        raise StaleFlowError(
            f"{station_key} live flow is {age_h:.1f}h stale (newest {readings[0][0]}) — "
            "EA flood-monitoring feed behind; rerun discover_flow_measures() if persistent")

    target = newest - timedelta(hours=24)
    recent = [v for dt, v in readings
              if (newest - _parse(dt)).total_seconds() <= 2 * 3600]
    prior = [v for dt, v in readings
             if abs((_parse(dt) - target).total_seconds()) <= 3600]
    if not recent or not prior:
        return False, None, None

    recent_m = sum(recent) / len(recent)
    prior_m = sum(prior) / len(prior)
    rising = prior_m > 0 and recent_m > prior_m * threshold
    return rising, round(recent_m, 3), round(prior_m, 3)


def discover_flow_measures():
    """Print paste-ready tw.config.FLOOD_MONITORING_FLOW entries for our stations.

    For each station it queries the flood-monitoring catalogue, keeps the 15-minute
    (period=900) flow measures with a non-null latest reading, and picks the freshest —
    skipping the dead duplicates some stations expose. Run this if a gauge's surge check
    starts raising StaleFlowError or 404s (EA occasionally renames a measure).
    """
    print("Paste-ready FLOOD_MONITORING_FLOW (freshest live 15-min flow per station):")
    for key in FLOOD_MONITORING_FLOW:
        ref = EA_STATIONS[key].ea_notation
        items = _get(f"{EA_FLOOD_MONITORING_ROOT}/id/measures",
                     {"stationReference": ref, "parameter": "flow"}).json().get("items", [])
        best = None
        for m in items:
            if m.get("period") != 900:
                continue
            lr = m.get("latestReading")
            lr_dt = lr.get("dateTime") if isinstance(lr, dict) else None
            if lr_dt and (best is None or lr_dt > best[1]):
                best = (m.get("@id", "").split("/id/measures/")[-1], lr_dt)
        if best:
            print(f'    "{key}": "{best[0]}",   # latest {best[1]}')
        else:
            print(f"    # {key}: NO live 15-min flow measure found for {ref}")


if __name__ == "__main__":
    discover_flow_measures()
