"""ThamesWatch API client — water-quality test results.

Public API at thames-watch.uk/api/v1, no authentication for read endpoints.
"""

import requests

from tw.config import THAMESWATCH_ROOT


def fetch_locations():
    """Return list of location dicts: testLocationId, name, stationId, latitude, longitude."""
    r = requests.get(f"{THAMESWATCH_ROOT}/locations", timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_results(location_id, from_date, to_date):
    """Return all test results for one location within an ISO date window."""
    r = requests.get(
        f"{THAMESWATCH_ROOT}/results/{location_id}",
        params={"fromDate": from_date, "toDate": to_date},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
