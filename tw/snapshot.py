"""Live-snapshot assembler.

build_snapshot() gathers, for a given date, exactly the inputs traffic_light_model_v3
.assess_safety() consumes — for every site — from live APIs and the topped-up CSVs.
This is the glue that replaces hand-assembling API calls before each model run.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from tw import config, ea_hydrology, thames_water
from tw.enrichment import calc_rain_metrics, season_of
from tw.paths import data_file

# Reused from the model — flow series loader and upstream-flow context.
from traffic_light_model_v3 import get_walton_flow, get_upstream_context


@dataclass
class SiteSnapshot:
    """Everything assess_safety() needs for one site, plus data-quality provenance."""

    site: str
    date: str
    # --- assess_safety() inputs ---
    rain_48h: float
    rain_7d: float
    dry_days: int
    season: str
    cso_active_48h: bool
    cso_hours_48h: float
    cso_active_monitors_str: str
    flow_m3s: float | None
    upstream_ctx: dict
    # --- provenance ---
    rain_station: str
    flow_data_date: str | None
    data_lag_days: int
    warnings: list = field(default_factory=list)


def _load_value_csv(path):
    """Load a date,value CSV into {date_str: float}."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("date"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        out[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return out


def _most_recent(series, on_or_before):
    """(date, value) of the latest reading on/before a date, or (None, None)."""
    candidates = [d for d in series if d <= on_or_before]
    if not candidates:
        return None, None
    d = max(candidates)
    return d, series[d]


def _topup_all(warnings):
    """Best-effort top-up of every flow and rain CSV. API hiccups become warnings."""
    for key, fname in {**config.FLOW_CSV, **config.RAIN_CSV}.items():
        try:
            ea_hydrology.topup_csv(key, data_file(fname))
        except Exception as exc:  # noqa: BLE001 — a transient API failure must not abort a prediction
            warnings.append(f"top-up of {key} failed: {exc}")


def build_snapshot(date=None, topup=True):
    """Assemble a SiteSnapshot for every configured site.

    `date` is an ISO date string (default: today UTC). `topup` refreshes the flow/rain
    CSVs first, so they stay current as a side effect of every prediction.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    date = date or today
    is_today = date >= today
    shared_warnings = []

    if topup:
        _topup_all(shared_warnings)

    check_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=12)
    end_of_day = check_dt.replace(hour=23, minute=59)

    # --- rain (one dict per gauge in use) ---
    rain_by_gauge = {}
    for key in {s.rain_station_key for s in config.SITES.values()}:
        rain_by_gauge[key] = _load_value_csv(data_file(config.RAIN_CSV[key]))

    # --- flow + upstream context (shared — the model feeds Walton flow to every site) ---
    walton_flow = get_walton_flow()
    exact = walton_flow.get(date)
    if exact is not None:
        flow_m3s, flow_data_date = exact, date
    else:
        flow_data_date, flow_m3s = _most_recent(walton_flow, date)
    lag = 0
    if flow_data_date:
        lag = (datetime.strptime(date, "%Y-%m-%d")
               - datetime.strptime(flow_data_date, "%Y-%m-%d")).days
    # Feed upstream context the freshest date with flow data — get_upstream_context
    # does an exact-date lookup, so the raw assessment date would yield zeros when
    # today's flow has not yet published (EA daily data lags 1-3 days).
    upstream_ctx = get_upstream_context(flow_data_date or date)

    # --- CSO (shared — global state; assess_safety filters per site) ---
    periods = thames_water.fetch_all_discharge_periods(now=end_of_day)
    active_48, _ = thames_water.was_cso_active(periods, check_dt, 48)
    hours_48, monitors_48 = thames_water.count_cso_hours(periods, check_dt, 48)
    active_72, _ = thames_water.was_cso_active(periods, check_dt, 72)
    monitors_str = "; ".join(f"{n}({h}h)" for n, h in monitors_48)

    if is_today:
        # History alerts lag — OR-in the live current-status feed.
        try:
            past48 = thames_water.monitors_active_past_48h()
            for it in past48:
                name = it.get("locationName", "")
                if name and name not in monitors_str:
                    monitors_str = f"{monitors_str}; {name}(live)".lstrip("; ")
                    active_48 = True
        except Exception as exc:  # noqa: BLE001
            shared_warnings.append(f"CSO current-status check failed: {exc}")

    # --- per-site assembly ---
    snapshots = {}
    for name, site in config.SITES.items():
        warnings = list(shared_warnings)
        if lag >= 2:
            warnings.append(f"flow data {lag} day(s) behind assessment date")
        if flow_m3s is None:
            warnings.append("no flow data available — flow rules inactive")

        metrics = calc_rain_metrics(rain_by_gauge[site.rain_station_key], date)
        snapshots[name] = SiteSnapshot(
            site=name, date=date,
            rain_48h=metrics["rain_48h"], rain_7d=metrics["rain_7d"],
            dry_days=metrics["dry_days"], season=season_of(date),
            cso_active_48h=active_48, cso_hours_48h=hours_48,
            cso_active_monitors_str=monitors_str,
            flow_m3s=flow_m3s, upstream_ctx=upstream_ctx,
            rain_station=site.rain_station_key,
            flow_data_date=flow_data_date, data_lag_days=lag,
            warnings=warnings,
        )
    return snapshots
