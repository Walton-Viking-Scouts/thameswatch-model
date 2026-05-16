"""Filesystem path resolution — resolved once, independent of current working directory.

Kills the bug where traffic_light_model_v3.load_data() used a hardcoded relative path
that only worked when run from the workspace root.
"""

import os

TW_DIR = os.path.dirname(os.path.abspath(__file__))   # .../thameswatch-analysis/tw
REPO_DIR = os.path.dirname(TW_DIR)                    # .../thameswatch-analysis
DATA_DIR = os.path.join(REPO_DIR, "data")             # CSVs live here post-migration


def data_file(name):
    """Resolve a data file by name.

    Prefers the data/ directory; falls back to the repo root so the function works
    both before and after the CSV migration (cleanup step).
    """
    in_data = os.path.join(DATA_DIR, name)
    if os.path.exists(in_data):
        return in_data
    return os.path.join(REPO_DIR, name)
