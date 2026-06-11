"""Feature engineering for the alternative model.

Design notes (evidence-based — see docs/RED-TEAM-2026-06.md §refs):
  - Rainfall is encoded as a *decayed antecedent precipitation index* (API), not a
    flat 48h total. API_t = k*API_{t-1} + P_t, computed from the daily Hogsmill gauge
    history. The literature puts the dominant river E. coli response at a ~24-48h lag
    with a multi-day memory; a single decay term captures that better than the
    24/48/72h/7d totals, which are mutually collinear.
  - CSO discharge is encoded as a *die-off-weighted load* term: spill-hours discounted
    by first-order decay over an assumed travel time, summed over site-relevant
    monitors. This lets a small, recent, nearby spill outweigh a large, old, distant one
    — which a raw hours/count cannot.
  - Seasonality is a sin/cos harmonic of day-of-year, not a 4-level categorical.
  - Site identity enters as one-hot dummies so the model can learn per-site baselines
    (the production model hard-codes these as "tiers").

All features are computed from data already in the repo (no network), so the harness
is reproducible offline.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta

import numpy as np

from tw.paths import data_file
from tw.config import CSO_MONITORS


# ---------------------------------------------------------------------------
# Raw data loaders (cached at module level)
# ---------------------------------------------------------------------------

_RAIN_CACHE: dict[str, dict[str, float]] = {}
_FLOW_CACHE: dict[str, dict[str, float]] = {}


def _load_series(filename: str, value_idx: int = 1) -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        with open(data_file(filename)) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("date"):
                    continue
                parts = line.split(",")
                if len(parts) > value_idx:
                    try:
                        out[parts[0]] = float(parts[value_idx])
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return out


def rain_series(name: str = "hogsmill_rain") -> dict[str, float]:
    if name not in _RAIN_CACHE:
        _RAIN_CACHE[name] = _load_series(f"{name}.csv")
    return _RAIN_CACHE[name]


def flow_series(name: str = "walton_flow") -> dict[str, float]:
    if name not in _FLOW_CACHE:
        _FLOW_CACHE[name] = _load_series(f"{name}.csv")
    return _FLOW_CACHE[name]


# ---------------------------------------------------------------------------
# Antecedent precipitation index
# ---------------------------------------------------------------------------

def antecedent_precip_index(date: str, k: float = 0.85, window: int = 21,
                            rain_name: str = "hogsmill_rain",
                            include_today: bool = False) -> float:
    """Decayed antecedent precipitation index ending the day *before* `date`.

    API = sum over the prior `window` days of rain_d * k**(age_in_days). With
    include_today=False the same-day rain is excluded (the production model's
    "prior days only" convention — a morning prediction has not yet seen the
    afternoon's rain).
    """
    rain = rain_series(rain_name)
    d0 = datetime.strptime(date, "%Y-%m-%d")
    start_age = 0 if include_today else 1
    total = 0.0
    for age in range(start_age, window + 1):
        d = (d0 - timedelta(days=age)).strftime("%Y-%m-%d")
        r = rain.get(d)
        if r:
            total += r * (k ** age)
    return total


# ---------------------------------------------------------------------------
# Die-off-weighted CSO load
# ---------------------------------------------------------------------------

# Site -> relevant river systems (mirrors the production SITE_CSO_RELEVANCE; kept
# local so the harness does not import the production model). Geography only.
SITE_CSO_RELEVANCE = {
    "Chertsey": ["ThamesUpstream"],
    "Walton Wharf": ["Wey", "ThamesUpstream"],
    "Ditton's Bend": ["Wey", "Mole", "ThamesUpstream"],
    "Kingston Albany Reach": ["Wey", "Mole", "Thames", "ThamesUpstream", "Hogsmill"],
    "Kingston HMT": ["Wey", "Mole", "ThamesUpstream", "Hogsmill"],
    "Teddington": ["Wey", "Mole", "Thames", "Minor", "ThamesUpstream", "Hogsmill"],
    "Hogsmill confluence": ["Wey", "Mole", "Thames", "Minor", "ThamesUpstream", "Hogsmill"],
    "Minima Yacht Club": ["Wey", "Mole", "Thames", "ThamesUpstream"],
}
DEFAULT_RELEVANCE = ["Wey", "Mole", "Thames", "Minor"]

_SYSTEM_OF = {m.name: m.river_system for m in CSO_MONITORS}


def _parse_monitors(s: str) -> list[tuple[str, float]]:
    """'Esher(9.0h); Leatherhead(22.2h)' -> [('Esher',9.0),('Leatherhead',22.2)]."""
    out = []
    if not s:
        return out
    for entry in s.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        name = entry.split("(")[0].strip()
        hours = 0.0
        if "(" in entry and "h" in entry:
            try:
                hours = float(entry.split("(")[1].split("h")[0])
            except (ValueError, IndexError):
                hours = 0.0
        out.append((name, hours))
    return out


def cso_features(site: str, monitors_str: str):
    """Return (relevant_count, relevant_hours, dieoff_load) for a site.

    dieoff_load discounts each monitor's spill-hours by a first-order decay over an
    assumed transport time. We do not have per-spill timing in this column (only
    48h-window totals), so the decay here is a simple monotone discount on hours
    (sqrt) that stops a single very long spill from dominating linearly — a pragmatic
    stand-in for the full die-off kernel, which needs the DischargeAlerts event
    stream (see the write-up's data-source recommendations).
    """
    relevant = set(SITE_CSO_RELEVANCE.get(site, DEFAULT_RELEVANCE))
    count = 0
    hours = 0.0
    load = 0.0
    for name, h in _parse_monitors(monitors_str):
        if _SYSTEM_OF.get(name) in relevant:
            count += 1
            hours += h
            load += math.sqrt(max(h, 0.0))
    return count, hours, load


# ---------------------------------------------------------------------------
# Feature matrix assembly
# ---------------------------------------------------------------------------

SITES_ORDERED = [
    "Walton Wharf", "Chertsey", "Kingston Albany Reach",
    "Kingston HMT", "Ditton's Bend", "Teddington",
]

# Continuous feature names, in order. Site one-hots appended after.
CONT_FEATURES = [
    "api",          # decayed antecedent precip index
    "rain_48h",     # kept — short-window first-flush
    "dry_days",     # antecedent dry build-up
    "log_flow",     # log1p Walton daily-mean flow
    "flow_surge",   # flow / prev-day flow (tributary flush proxy)
    "cso_count",    # site-relevant active monitors
    "cso_load",     # die-off-weighted spill load
    "sin_doy",      # seasonality
    "cos_doy",
]


def load_rows():
    with open(data_file("thameswatch_correlation_with_cso.csv")) as f:
        return list(csv.DictReader(f))


def _flow_for(date: str):
    walton = flow_series("walton_flow")
    f = walton.get(date)
    if f is None:
        return None, 1.0
    prev = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    fp = walton.get(prev)
    surge = (f / fp) if (fp and fp > 0) else 1.0
    return f, surge


def build_feature_row(row: dict, api_k: float = 0.85) -> dict:
    """Build a single feature dict (plus metadata) for one test row."""
    site = row["site"]
    date = row["date"]
    rain_48h = float(row["rain_48h"]) if row.get("rain_48h") else 0.0
    dry_days = float(row["dry_days"]) if row.get("dry_days") else 0.0
    monitors = row.get("cso_active_monitors", "")

    api = antecedent_precip_index(date, k=api_k)
    flow, surge = _flow_for(date)
    log_flow = math.log1p(flow) if flow is not None else math.log1p(40.0)  # median-ish fallback
    cso_count, cso_hours, cso_load = cso_features(site, monitors)

    doy = datetime.strptime(date, "%Y-%m-%d").timetuple().tm_yday
    sin_doy = math.sin(2 * math.pi * doy / 365.25)
    cos_doy = math.cos(2 * math.pi * doy / 365.25)

    feats = {
        "api": api,
        "rain_48h": rain_48h,
        "dry_days": dry_days,
        "log_flow": log_flow,
        "flow_surge": surge,
        "cso_count": float(cso_count),
        "cso_load": cso_load,
        "sin_doy": sin_doy,
        "cos_doy": cos_doy,
    }
    return {
        "site": site,
        "date": date,
        "ec": float(row["ec"]),
        "unsafe": float(row["ec"]) > 500,
        "dangerous": float(row["ec"]) > 2000,
        "features": feats,
    }


def build_dataset(api_k: float = 0.85):
    """Return list of feature-rows sorted by date (then site)."""
    rows = [build_feature_row(r, api_k=api_k) for r in load_rows()]
    rows.sort(key=lambda r: (r["date"], r["site"]))
    return rows


def to_matrix(rows, sites=None):
    """Convert feature-rows to (X, y_unsafe, y_dangerous, feature_names).

    X columns: CONT_FEATURES (standardized later by the model) + site one-hots.
    """
    if sites is None:
        sites = SITES_ORDERED
    site_index = {s: i for i, s in enumerate(sites)}
    n_cont = len(CONT_FEATURES)
    n_site = len(sites)
    X = np.zeros((len(rows), n_cont + n_site))
    y = np.zeros(len(rows))
    yd = np.zeros(len(rows))
    for i, r in enumerate(rows):
        f = r["features"]
        for j, name in enumerate(CONT_FEATURES):
            X[i, j] = f[name]
        si = site_index.get(r["site"])
        if si is not None:
            X[i, n_cont + si] = 1.0
        y[i] = r["unsafe"]
        yd[i] = r["dangerous"]
    names = list(CONT_FEATURES) + [f"site::{s}" for s in sites]
    return X, y, yd, names
