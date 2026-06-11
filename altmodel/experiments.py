"""Targeted experiments behind the red-team recommendations.

  1. pos_weight sweep — the asymmetric-cost lever. Shows the false-safe / GREEN-volume
     trade-off the production rules can't expose (they have a single fixed operating
     point). This is the single most actionable knob (USGS: tune the threshold below 0.5).
  2. Feature ablations — what actually carries the model. Honest accounting of which
     engineered features earn their place.
  3. Forecast mode — refit using only inputs knowable a day ahead (rain, season, site;
     NO same-day CSO discharge), to quantify how much skill a true day-ahead forecast
     retains. The dominant predictor (CSO) is the hardest to forecast, so this is the
     real ceiling on forecasting.

Run:  python3 -m altmodel.experiments
"""
from __future__ import annotations

import numpy as np

from altmodel.features import build_dataset, to_matrix, CONT_FEATURES, SITES_ORDERED
from altmodel.models import LogisticModel
from altmodel.evaluate import (
    forward_chaining_logistic, colour_metrics, roc_auc, pr_auc, brier,
    best_thresholds, proba_to_colour,
)


def _fc_with_columns(rows, keep_cont, l2=2.0, pos_weight=3.0):
    """Forward-chaining OOS using only a subset of continuous features (+ all sites)."""
    keep_idx = [CONT_FEATURES.index(c) for c in keep_cont]
    n_cont = len(CONT_FEATURES)

    def subset(X):
        site_cols = X[:, n_cont:]
        return np.hstack([X[:, keep_idx], site_cols])

    dates = sorted({r["date"] for r in rows})
    n = len(dates); warm = int(n * 0.4)
    bounds = [warm + int((n - warm) * b / 5) for b in range(6)]
    P, Y, YD, COL = [], [], [], []
    for b in range(5):
        cut = dates[bounds[b]] if bounds[b] < n else dates[-1]
        tdates = set(dates[bounds[b]:bounds[b + 1]])
        tr = [r for r in rows if r["date"] < cut]
        te = [r for r in rows if r["date"] in tdates]
        if not tr or not te:
            continue
        Xtr, ytr, _, _ = to_matrix(tr); Xte, yte, yde, _ = to_matrix(te)
        m = LogisticModel(l2=l2, pos_weight=pos_weight).fit(subset(Xtr), ytr)
        ptr = m.predict_proba(subset(Xtr))
        tg, trd = best_thresholds(ptr, ytr)
        pte = m.predict_proba(subset(Xte))
        for i in range(len(te)):
            P.append(float(pte[i])); Y.append(float(yte[i])); YD.append(float(yde[i]))
            COL.append(proba_to_colour(pte[i], tg, trd))
    return P, Y, YD, COL


def line(label, P, Y, YD, COL):
    m = colour_metrics(COL, Y, YD)
    print(f"  {label:34s} GREEN={m['n_green']:>3} "
          f"(false-safe {m['green_unsafe']}={m['green_unsafe_pct']:.0f}%, dang {m['green_dangerous']}) "
          f"sens={m['sensitivity_unsafe']*100:.0f}% cost={m['mean_cost']:.3f} "
          f"AUC={roc_auc(Y,P):.2f} PR={pr_auc(Y,P):.2f}")
    return m


def main():
    rows = build_dataset(api_k=0.85)

    print("=== 1. pos_weight sweep (asymmetric-cost lever) ===")
    print("    higher pos_weight => unsafe class up-weighted => fewer false-safe GREENs\n")
    for pw in [1.0, 2.0, 3.0, 5.0, 8.0, 12.0]:
        P, Y, YD, COL, meta = forward_chaining_logistic(rows, l2=2.0, pos_weight=pw)
        line(f"pos_weight={pw}", P, Y, YD, COL)

    print("\n=== 2. feature ablations (forward-chaining OOS, pos_weight=3) ===\n")
    full = list(CONT_FEATURES)
    ablations = {
        "ALL features": full,
        "no CSO (cso_load,cso_count)": [c for c in full if not c.startswith("cso")],
        "no flow (log_flow,surge)": [c for c in full if c not in ("log_flow", "flow_surge")],
        "no API (decayed precip)": [c for c in full if c != "api"],
        "no seasonality (sin/cos)": [c for c in full if c not in ("sin_doy", "cos_doy")],
        "rain_48h + season + site only": ["rain_48h", "sin_doy", "cos_doy"],
        "CSO + rain + season only": ["cso_load", "cso_count", "rain_48h", "sin_doy", "cos_doy"],
    }
    for label, cols in ablations.items():
        P, Y, YD, COL = _fc_with_columns(rows, cols)
        line(label, P, Y, YD, COL)

    print("\n=== 3. forecast mode — only day-ahead-knowable inputs ===")
    print("    drops same-day CSO discharge + measured flow; keeps rain(forecastable)+season+site\n")
    forecastable = ["api", "rain_48h", "dry_days", "sin_doy", "cos_doy"]
    P, Y, YD, COL = _fc_with_columns(rows, forecastable, pos_weight=3.0)
    m_fc = line("forecast (rain+season+site)", P, Y, YD, COL)
    P, Y, YD, COL = _fc_with_columns(rows, forecastable, pos_weight=8.0)
    line("forecast, pos_weight=8 (cautious)", P, Y, YD, COL)
    # nowcast (full, same-day) reference
    P, Y, YD, COL, meta = forward_chaining_logistic(rows, l2=2.0, pos_weight=3.0)
    line("nowcast reference (full, same-day)", P, Y, YD, COL)


if __name__ == "__main__":
    main()
