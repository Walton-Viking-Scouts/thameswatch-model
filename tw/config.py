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


@dataclass(frozen=True)
class CSOMonitor:
    """A Thames Water EDM (storm overflow) monitor near our stretch."""

    name: str                   # exact Thames Water locationName
    river_system: str           # "Wey" | "Mole" | "Thames" | "Minor"


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
}


# --- Thames Water CSO monitors ----------------------------------------------
# 14 monitors in the Chertsey-Teddington catchment. river_system classification
# matches traffic_light_model_v3.count_active_river_systems().

CSO_MONITORS = [
    CSOMonitor("Woking", "Wey"),
    CSOMonitor("Ripley", "Wey"),
    CSOMonitor("Weybridge", "Wey"),
    CSOMonitor("Dartnell Park, Byfleet", "Minor"),
    CSOMonitor("Commonside", "Minor"),
    CSOMonitor("Cobham Bridge, Adj Cobham PS", "Mole"),
    CSOMonitor("Stoke Road, Cobham", "Mole"),
    CSOMonitor("Esher", "Mole"),
    CSOMonitor("Leatherhead", "Mole"),
    CSOMonitor("River Lane", "Mole"),
    CSOMonitor("Amyand Park Road, Twickenham", "Thames"),
    CSOMonitor("Old Palace Lane", "Thames"),
    CSOMonitor("Portsmouth Road, Uxbridge Road", "Thames"),
    CSOMonitor("Kingston Main", "Thames"),
]

CSO_MONITOR_NAMES = [m.name for m in CSO_MONITORS]


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
}

# ThamesWatch API locationName -> canonical model site name
SITE_BY_THAMESWATCH_LOCATION = {s.thameswatch_location: name for name, s in SITES.items()}


# --- Geographic bounds (Chertsey to Teddington, OS easting/northing) ---------
GEO_BOUNDS = {
    "min_easting": 503000, "max_easting": 518000,
    "min_northing": 160000, "max_northing": 172000,
}
