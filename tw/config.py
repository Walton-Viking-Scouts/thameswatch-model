"""Central registry — single source of truth for APIs, stations, monitors, and sites.

Consolidates constants previously scattered across fetch_cso_history.py,
fetch_cso_outfalls.py, fetch_thameswatch.py, refresh_correlation.py, and
traffic_light_model_v3.py.

Kept as a Python module (not JSON/YAML): config is developer-edited only, needs
structured records with derived helpers, and fails fast on typos.
"""

from dataclasses import dataclass

# --- API roots ---
EA_HYDROLOGY_ROOT = "https://environment.data.gov.uk/hydrology"
EA_FLOOD_MONITORING_ROOT = "https://environment.data.gov.uk/flood-monitoring"
THAMES_WATER_ROOT = "https://api.thameswater.co.uk"
THAMESWATCH_ROOT = "https://thames-watch.uk/api/v1"


@dataclass(frozen=True)
class EAStation:
    """An Environment Agency Hydrology gauging station (flow or rainfall)."""

    key: str                    # short handle, e.g. "walton", "cranleigh_rain"
    name: str                   # human label
    ea_notation: str            # EA station notation, e.g. "3100TH" ("-" if unknown)
    kind: str                   # "flow" | "rainfall"
    station_guid: str | None    # EA station GUID — None until rediscovered
    measure_id: str | None      # full daily (-86400-) measure id — None until rediscovered

    @property
    def readings_url(self):
        if not self.measure_id:
            return None
        return f"{EA_HYDROLOGY_ROOT}/id/measures/{self.measure_id}/readings.json"

    @property
    def measures_url(self):
        if not self.station_guid:
            return None
        return f"{EA_HYDROLOGY_ROOT}/id/stations/{self.station_guid}/measures.json"


# Valid CSO river-system classifications. The model keys off these exact strings
# (traffic_light_model_v3.count_active_river_systems, SITE_CSO_RELEVANCE, and the
# UPSTREAM_THAMES_NAMES filter below), so a typo must fail loudly at import rather than
# silently drop a monitor from every system it should belong to.
RIVER_SYSTEMS = frozenset({"Wey", "Mole", "Thames", "Minor", "ThamesUpstream", "Hogsmill"})


@dataclass(frozen=True)
class CSOMonitor:
    """A Thames Water EDM (storm overflow) monitor near our stretch.

    easting/northing are the monitor's OS grid coordinates from the EDM
    /discharge/status feed, recorded as provenance — the geography each monitor's
    river_system classification rests on. They are not read by the model itself; the
    upstream-of-Chertsey near/far distance cut lives in fetch_upstream_cso.py, which
    works on the live feed.
    """

    name: str                   # exact Thames Water locationName
    river_system: str           # one of RIVER_SYSTEMS
    easting: int                # OS grid easting (from EDM /discharge/status)
    northing: int               # OS grid northing

    def __post_init__(self):
        if self.river_system not in RIVER_SYSTEMS:
            raise ValueError(
                f"CSOMonitor {self.name!r}: unknown river_system {self.river_system!r} "
                f"(expected one of {sorted(RIVER_SYSTEMS)})")


@dataclass(frozen=True)
class Site:
    """A ThamesWatch water-quality test site that the model predicts for."""

    name: str                   # canonical model site name
    thameswatch_location: str   # exact ThamesWatch API locationName
    lat: float
    long: float
    rain_station_key: str       # per-catchment rain gauge feeding the model


# --- EA Hydrology stations ---------------------------------------------------
# Daily measure id pattern: {guid}-{flow-m|rainfall-t}-86400-{m3s|mm}-qualified
# GUIDs for mole/staines/reading are unknown — rediscovered via ea_hydrology.search_stations.

EA_STATIONS = {
    "walton": EAStation(
        "walton", "Thames at Walton", "3100TH", "flow",
        "b92a2ca3-4eb9-4a8f-b82f-8bbc2a1dfbc9",
        "b92a2ca3-4eb9-4a8f-b82f-8bbc2a1dfbc9-flow-m-86400-m3s-qualified"),
    "wey": EAStation(
        "wey", "Wey at Weybridge", "3090TH", "flow",
        "2629abeb-e504-49f7-9996-080f37e15930",
        "2629abeb-e504-49f7-9996-080f37e15930-flow-m-86400-m3s-qualified"),
    "mole": EAStation(
        "mole", "Mole at Esher", "3290TH", "flow",
        "024f218d-9a70-43b7-8ea2-7d038eeb2cff",
        "024f218d-9a70-43b7-8ea2-7d038eeb2cff-flow-m-86400-m3s-qualified"),
    "staines": EAStation(
        "staines", "Thames at Staines", "2900TH", "flow",
        "305bad2c-6aa6-417d-a101-698edc850bbd",
        "305bad2c-6aa6-417d-a101-698edc850bbd-flow-m-86400-m3s-qualified"),
    "reading": EAStation(
        "reading", "Thames at Reading", "2200TH", "flow",
        "f44bf96d-3953-4fec-88bd-30ef4e12e523",
        "f44bf96d-3953-4fec-88bd-30ef4e12e523-flow-m-86400-m3s-qualified"),
    # Kingston (3399TH) is used only for the live flow display (the downstream sites'
    # nearest flow gauge); no Hydrology daily series is loaded for it, hence no GUID.
    "kingston": EAStation(
        "kingston", "Thames at Kingston", "3399TH", "flow", None, None),
    "hogsmill_rain": EAStation(
        "hogsmill_rain", "Hogsmill rain (Kingston)", "-", "rainfall",
        "a04aa8e8-45a2-4d8d-9983-7a55330693b0",
        "a04aa8e8-45a2-4d8d-9983-7a55330693b0-rainfall-t-86400-mm-qualified"),
    "cranleigh_rain": EAStation(
        "cranleigh_rain", "Cranleigh rain (Wey catchment)", "-", "rainfall",
        "f8093480-7cda-45e8-8e0a-7b1723b4f989",
        "f8093480-7cda-45e8-8e0a-7b1723b4f989-rainfall-t-86400-mm-qualified"),
    "burstow_rain": EAStation(
        "burstow_rain", "Burstow rain (Mole catchment)", "-", "rainfall",
        "8864da31-6c81-4cb1-bde9-d4ca73423222",
        "8864da31-6c81-4cb1-bde9-d4ca73423222-rainfall-t-86400-mm-qualified"),
    "reading_rain": EAStation(
        "reading_rain", "Reading University rain (Thames upstream)", "-", "rainfall",
        "0a37c7cf-0c60-4024-a5ef-b9c6c7c14600",
        "0a37c7cf-0c60-4024-a5ef-b9c6c7c14600-rainfall-t-86400-mm-qualified"),
}

# CSV filenames for the flow stations the model loads (traffic_light_model_v3.FLOW_FILES).
FLOW_CSV = {
    "walton": "walton_flow.csv",
    "wey": "wey_weybridge_flow.csv",
    "mole": "mole_esher_flow.csv",
    "staines": "thames_staines_flow.csv",
    "reading": "thames_reading_flow.csv",
}
RAIN_CSV = {
    "hogsmill_rain": "hogsmill_rain.csv",
    "cranleigh_rain": "cranleigh_rain.csv",
    "burstow_rain": "burstow_rain.csv",
    "reading_rain": "reading_rain.csv",
}

# Live 15-minute flow measures on the EA flood-monitoring API, keyed by station_key.
# The Hydrology API's daily mean lags ~2 days and its 15-minute *flow* series is staler
# still (it froze ~2026-04-15 for these gauges; rainfall 15-min is unaffected). Genuinely
# live flow telemetry — current to ~1h — is on the flood-monitoring API instead, and the
# model uses it only for tributary-surge detection (absolute thresholds stay on the
# Hydrology daily mean). Measure ids are not string-buildable — the notation varies per
# station and some carry a dead duplicate with no readings — so they are discovered and
# frozen here via tw.flood_monitoring.discover_flow_measures(); re-run that if a gauge's
# surge check starts raising StaleFlowError or 404s.
FLOOD_MONITORING_FLOW = {
    "walton": "3100TH-flow--i-15_min-m3_s",
    "wey": "3090TH-flow-water-i-15_min-m3_s",
    "mole": "3290TH-flow--i-15_min-m3_s",
    "staines": "2900TH-flow--Mean-15_min-m3_s",
    "reading": "2200TH-flow--Mean-15_min-m3_s",
    "kingston": "3399TH-flow-water-i-15_min-m3_s",
}

# Which live flow gauge to display as each site's "current flow" (safety context — high
# flow means strong currents regardless of water quality). The Thames gains volume
# downstream as the Wey and Mole join, so sites map to their nearest mainstem gauge.
# Teddington is the tidal limit with no comparable flow gauge, so it borrows Kingston
# (the nearest gauge upstream). This is display-only — the model's flow thresholds still
# use the Walton daily mean (see traffic_light_model_v3.SITE_FLOW_CONFIG).
SITE_LIVE_FLOW_GAUGE = {
    "Chertsey": "staines",
    "Walton Wharf": "walton",
    "Ditton's Bend": "kingston",
    "Kingston Albany Reach": "kingston",
    "Kingston HMT": "kingston",
    "Teddington": "kingston",
    "Hogsmill confluence": "kingston",
    "Minima Yacht Club": "kingston",
}


# --- Thames Water CSO monitors ----------------------------------------------
# 17 monitors. Coordinates and river_system are discovered from the EDM
# /discharge/status feed (archive/fetch_cso_outfalls.py for the in-stretch set;
# fetch_upstream_cso.py for the upstream-of-Chertsey set) and then frozen here — the
# same discover-once-then-hard-code pattern as the EAStation GUIDs above. river_system
# classification drives traffic_light_model_v3.count_active_river_systems(), which reads
# this list directly (single source of truth — no parallel keyword table in the model).
#
# In-stretch monitors (Chertsey -> Teddington), east of the Chertsey test site (~505000):
CSO_MONITORS = [
    CSOMonitor("Woking", "Wey", 503270, 157520),
    CSOMonitor("Ripley", "Wey", 504490, 157320),
    CSOMonitor("Weybridge", "Wey", 506770, 163140),
    CSOMonitor("Dartnell Park, Byfleet", "Minor", 505600, 162100),
    CSOMonitor("Commonside", "Minor", 513300, 156200),
    CSOMonitor("Cobham Bridge, Adj Cobham PS", "Mole", 509890, 160760),
    CSOMonitor("Stoke Road, Cobham", "Mole", 511280, 159810),
    CSOMonitor("Esher", "Mole", 513030, 165980),
    CSOMonitor("Leatherhead", "Mole", 514690, 158030),
    CSOMonitor("River Lane", "Mole", 514700, 157100),
    CSOMonitor("Amyand Park Road, Twickenham", "Thames", 516700, 173300),
    CSOMonitor("Old Palace Lane", "Thames", 517308, 174821),
    CSOMonitor("Portsmouth Road, Uxbridge Road", "Thames", 517670, 168010),
    CSOMonitor("Kingston Main", "Thames", 517800, 169600),

    # Hogsmill STW (Berrylands) storm overflow. The EDM monitor named "Hogsmill"
    # (permit CASM.0042, receivingWaterCourse "River Hogsmill") sits on the Hogsmill
    # ~2 km up from where that river joins the Thames at Kingston (~51.409). Its own
    # river_system "Hogsmill" so the relevance map can give it the exact downstream reach:
    # only sites AT or BELOW the Kingston confluence (Hogsmill confluence, Albany Reach,
    # Kingston HMT, Teddington) see it; Minima and everything upstream do not. Coordinates
    # here are the works itself (the discharge point on the Hogsmill), recorded as
    # provenance — the Thames-reach relevance lives in SITE_CSO_RELEVANCE, not these.
    CSOMonitor("Hogsmill", "Hogsmill", 519200, 168560),

    # Upstream-of-Chertsey Thames mainstem overflows. These sit ABOVE the whole monitored
    # stretch, so they are the geographically-correct CSO predictor for Chertsey (whose
    # relevance was previously the Wey, which actually joins downstream at Weybridge).
    # Discovered by fetch_upstream_cso.py; only the two CLOSEST to Chertsey are kept.
    # An ablation (experiment_upstream_weighting.py) showed the three farther monitors
    # (Reading 472800, Friday St Henley 476300, Hambleden 478600 — 26-32 km up, beyond
    # ~1-2 days of E. coli die-off and dilution) caught zero extra unsafe days while
    # removing 7 safe days from GREEN, i.e. pure false-conservatism. Windsor (~5 km) and
    # Little Marlow (~17 km) capture the full upstream-CSO signal on their own.
    CSOMonitor("Little Marlow", "ThamesUpstream", 487710, 186960),
    CSOMonitor("Windsor", "ThamesUpstream", 499700, 175000),
]

CSO_MONITOR_NAMES = [m.name for m in CSO_MONITORS]
UPSTREAM_THAMES_NAMES = [m.name for m in CSO_MONITORS if m.river_system == "ThamesUpstream"]


# --- Test sites --------------------------------------------------------------
# rain_station_key: all sites use the Hogsmill gauge. A per-catchment mapping
# (Cranleigh/Burstow headwater gauges) was tested and re-validated 2026-05-16 — it
# slightly underperformed (GREEN 95%->93%, RED 81%->78%). The rain_48h column models
# LOCAL runoff at the test site; upstream-rain effects on CSOs are already captured by
# the separate Thames Water CSO feed. A central Thames-valley gauge therefore beats
# headwater gauges here. Single-Hogsmill confirmed as the accurate choice.

SITES = {
    "Walton Wharf": Site(
        "Walton Wharf", "Walton On Thames (Walton Warf)",
        51.38988, -0.42325, "hogsmill_rain"),
    "Chertsey": Site(
        "Chertsey", "Chertsey (Paxmead River Base)",
        51.38674, -0.47055, "hogsmill_rain"),
    "Kingston Albany Reach": Site(
        "Kingston Albany Reach", "Kingston (Albany Reach)",
        51.422497, -0.305844, "hogsmill_rain"),
    "Kingston HMT": Site(
        "Kingston HMT", "Kingston (Half Mile Tree)",
        51.424278, -0.307032, "hogsmill_rain"),
    "Ditton's Bend": Site(
        "Ditton's Bend", "Ditton’s Bend",   # ThamesWatch API uses a curly apostrophe
        51.39138, -0.327254, "hogsmill_rain"),
    "Teddington": Site(
        "Teddington", "Teddington (Hawker Centre)",
        51.42702, -0.3108, "hogsmill_rain"),
    "Hogsmill confluence": Site(
        "Hogsmill confluence", "Hogsmill confluence",
        51.409377, -0.308450, "hogsmill_rain"),
    "Minima Yacht Club": Site(
        "Minima Yacht Club", "Minima Yacht Club",
        51.407652, -0.308423, "hogsmill_rain"),
}

# ThamesWatch API locationName -> canonical model site name
SITE_BY_THAMESWATCH_LOCATION = {s.thameswatch_location: name for name, s in SITES.items()}


# --- Upstream catchments (for the upstream-watch display) --------------------
# Each catchment: a headwater rain gauge, and the flow station where that
# catchment's water reaches our stretch. Headwater rain takes ~1-3 days to
# arrive — this is a display/early-warning view, not a model input (the model
# already reads the upstream signal from flow).

CATCHMENTS = {
    "Wey": {
        "rain_station": "cranleigh_rain", "flow_station": "wey",
        "joins": "the Thames at Weybridge, above Walton",
    },
    "Mole": {
        "rain_station": "burstow_rain", "flow_station": "mole",
        "joins": "the Thames at East Molesey, above Kingston",
    },
    "Thames": {
        "rain_station": "reading_rain", "flow_station": "reading",
        "joins": "the stretch from upstream (Reading and beyond)",
    },
}


# --- Geographic bounds (Chertsey to Teddington, OS easting/northing) ---------
GEO_BOUNDS = {
    "min_easting": 503000, "max_easting": 518000,
    "min_northing": 160000, "max_northing": 172000,
}
