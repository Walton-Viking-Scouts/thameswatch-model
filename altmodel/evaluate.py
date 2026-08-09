"""Honest evaluation harness — the core red-team contribution.

What makes it "honest", versus the production `tw/model.py --validate`:

  1. Out-of-sample. Every prediction scored here is made by a model that never saw
     that row in training. Two schemes:
       - forward-chaining (expanding window) by date — the operational reality of a
         live forecaster (only the past is known);
       - leave-one-site-out — tests geographic transfer (RDMAI's documented failure).
     The production validation is in-sample: its rules were hand-tuned on the same
     239 rows it then reports accuracy on.

  2. Beats a floor. Persistence ("it was bad last time") and rainfall-threshold
     baselines are scored alongside. USGS operational doctrine: a model with no edge
     over persistence has no demonstrated skill.

  3. Asymmetric cost. A false GREEN on unsafe water is weighted ~10x a needless
     caution, via an explicit, exposed cost matrix — and the 3-colour thresholds are
     *chosen* to minimise that cost on training data, not eyeballed.

Run:  python3 -m altmodel.evaluate
"""
from __future__ import annotations

import json
import numpy as np

from tw.paths import data_file
from altmodel.features import build_dataset, to_matrix, SITES_ORDERED, CONT_FEATURES
from altmodel.models import (
    LogisticModel, PersistenceBaseline, RainThresholdBaseline, BaseRateBaseline,
)

# --- Cost matrix: cost[colour][outcome] -------------------------------------
# outcome: "unsafe" (EC>500) or "safe". A false GREEN on unsafe water dominates.
COST = {
    "GREEN": {"unsafe": 10.0, "safe": 0.0},
    "AMBER": {"unsafe": 2.0,  "safe": 1.0},
    "RED":   {"unsafe": 0.0,  "safe": 3.0},
}
COLOURS = ["GREEN", "AMBER", "RED"]


# ---------------------------------------------------------------------------
# Metrics (no sklearn)
# ---------------------------------------------------------------------------

def roc_auc(y, p):
    y = np.asarray(y); p = np.asarray(p)
    pos = p[y > 0.5]; neg = p[y < 0.5]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Mann-Whitney U / AUC
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    r_pos = ranks[:len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def pr_auc(y, p):
    y = np.asarray(y); p = np.asarray(p)
    order = np.argsort(-p)
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    total_pos = y.sum()
    if total_pos == 0:
        return float("nan")
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / total_pos
    # average precision (step integral over recall)
    ap = 0.0
    prev_r = 0.0
    for pr, rc in zip(precision, recall):
        ap += pr * (rc - prev_r)
        prev_r = rc
    return ap


def brier(y, p):
    y = np.asarray(y); p = np.asarray(p)
    return float(np.mean((p - y) ** 2))


def proba_to_colour(p, t_green, t_red):
    if p < t_green:
        return "GREEN"
    if p < t_red:
        return "AMBER"
    return "RED"


def best_thresholds(p, y, grid=None):
    """Pick (t_green, t_red) minimizing mean cost on (p, y). y in {0,1} unsafe."""
    if grid is None:
        grid = np.linspace(0.02, 0.98, 49)
    best = (0.2, 0.6)
    best_cost = float("inf")
    for tg in grid:
        for tr in grid:
            if tr < tg:
                continue
            c = 0.0
            for pi, yi in zip(p, y):
                colour = proba_to_colour(pi, tg, tr)
                c += COST[colour]["unsafe" if yi > 0.5 else "safe"]
            c /= len(y)
            if c < best_cost:
                best_cost = c
                best = (tg, tr)
    return best


def colour_metrics(colours, y_unsafe, y_dangerous=None):
    """Confusion-style metrics for a list of colour verdicts."""
    colours = list(colours)
    y = np.asarray(y_unsafe)
    n = len(colours)
    res = {c: {"n": 0, "unsafe": 0, "dangerous": 0} for c in COLOURS}
    for i, col in enumerate(colours):
        res[col]["n"] += 1
        if y[i] > 0.5:
            res[col]["unsafe"] += 1
        if y_dangerous is not None and y_dangerous[i] > 0.5:
            res[col]["dangerous"] += 1
    n_unsafe = int(y.sum())
    green_unsafe = res["GREEN"]["unsafe"]
    # sensitivity for unsafe = fraction of unsafe NOT cleared as GREEN
    caught = sum(res[c]["unsafe"] for c in ("AMBER", "RED"))
    sensitivity = caught / n_unsafe if n_unsafe else float("nan")
    n_safe = n - n_unsafe
    safe_green = res["GREEN"]["n"] - res["GREEN"]["unsafe"]
    specificity_green = safe_green / n_safe if n_safe else float("nan")  # safe water correctly cleared
    cost = np.mean([COST[col]["unsafe" if y[i] > 0.5 else "safe"]
                    for i, col in enumerate(colours)])
    out = {
        "n": n,
        "n_green": res["GREEN"]["n"],
        "green_unsafe": green_unsafe,
        "green_unsafe_pct": green_unsafe / res["GREEN"]["n"] * 100 if res["GREEN"]["n"] else 0.0,
        "green_dangerous": res["GREEN"]["dangerous"],
        "n_red": res["RED"]["n"],
        "red_unsafe_pct": res["RED"]["unsafe"] / res["RED"]["n"] * 100 if res["RED"]["n"] else 0.0,
        "sensitivity_unsafe": sensitivity,
        "specificity_green": specificity_green,
        "mean_cost": float(cost),
    }
    return out


# ---------------------------------------------------------------------------
# Current production v3 rules (fixed) — for reference (in-sample)
# ---------------------------------------------------------------------------

def v3_colours(rows):
    """Run the production rules. Imported lazily to avoid hard coupling."""
    from tw import model as prod
    import csv as _csv
    # The production run_v3 expects the raw CSV dict rows; re-read them keyed by (site,date).
    with open(data_file("thameswatch_correlation_with_cso.csv")) as f:
        raw = {(r["site"], r["date"]): r for r in _csv.DictReader(f)}
    out = []
    for r in rows:
        raw_row = raw.get((r["site"], r["date"]))
        out.append(prod.run_v3(raw_row) if raw_row else "AMBER")
    return out


# ---------------------------------------------------------------------------
# CV drivers
# ---------------------------------------------------------------------------

def forward_chaining_logistic(rows, l2=2.0, pos_weight=3.0, warmup_frac=0.4,
                              n_blocks=5, sites=None):
    """Expanding-window CV for the logistic model. Returns pooled OOS (p, y, colour)."""
    dates = sorted({r["date"] for r in rows})
    n = len(dates)
    warm = int(n * warmup_frac)
    bounds = [warm + int((n - warm) * b / n_blocks) for b in range(n_blocks + 1)]
    pooled_p, pooled_y, pooled_yd, pooled_col, pooled_meta = [], [], [], [], []
    for b in range(n_blocks):
        train_cut = dates[bounds[b]] if bounds[b] < n else dates[-1]
        test_lo = bounds[b]
        test_hi = bounds[b + 1]
        test_dates = set(dates[test_lo:test_hi])
        train_rows = [r for r in rows if r["date"] < train_cut]
        test_rows = [r for r in rows if r["date"] in test_dates]
        if not train_rows or not test_rows:
            continue
        Xtr, ytr, _, names = to_matrix(train_rows, sites)
        Xte, yte, yde, _ = to_matrix(test_rows, sites)
        model = LogisticModel(l2=l2, pos_weight=pos_weight).fit(Xtr, ytr)
        ptr = model.predict_proba(Xtr)
        tg, tr = best_thresholds(ptr, ytr)
        pte = model.predict_proba(Xte)
        for i, r in enumerate(test_rows):
            pooled_p.append(float(pte[i]))
            pooled_y.append(float(yte[i]))
            pooled_yd.append(float(yde[i]))
            pooled_col.append(proba_to_colour(pte[i], tg, tr))
            pooled_meta.append((r["site"], r["date"], r["ec"]))
    return pooled_p, pooled_y, pooled_yd, pooled_col, pooled_meta


def forward_chaining_baseline(rows, baseline_cls, warmup_frac=0.4, n_blocks=5):
    """Expanding-window CV for a row-wise baseline. Pooled OOS (p, y)."""
    dates = sorted({r["date"] for r in rows})
    n = len(dates)
    warm = int(n * warmup_frac)
    bounds = [warm + int((n - warm) * b / n_blocks) for b in range(n_blocks + 1)]
    pooled_p, pooled_y, pooled_yd, pooled_col = [], [], [], []
    for b in range(n_blocks):
        train_cut = dates[bounds[b]] if bounds[b] < n else dates[-1]
        test_lo, test_hi = bounds[b], bounds[b + 1]
        test_dates = set(dates[test_lo:test_hi])
        train_rows = [r for r in rows if r["date"] < train_cut]
        test_rows = [r for r in rows if r["date"] in test_dates]
        if not train_rows or not test_rows:
            continue
        bl = baseline_cls().fit(train_rows)
        ptr = np.array([bl.predict_proba_row(r) for r in train_rows])
        ytr = np.array([r["unsafe"] for r in train_rows])
        tg, tr = best_thresholds(ptr, ytr)
        for r in test_rows:
            p = bl.predict_proba_row(r)
            pooled_p.append(float(p))
            pooled_y.append(float(r["unsafe"]))
            pooled_yd.append(float(r["dangerous"]))
            pooled_col.append(proba_to_colour(p, tg, tr))
    return pooled_p, pooled_y, pooled_yd, pooled_col


def leave_one_site_out_logistic(rows, l2=2.0, pos_weight=3.0, sites=None):
    if sites is None:
        sites = SITES_ORDERED
    pooled_p, pooled_y, pooled_yd, pooled_col, pooled_meta = [], [], [], [], []
    for held in sites:
        train_rows = [r for r in rows if r["site"] != held]
        test_rows = [r for r in rows if r["site"] == held]
        if not test_rows:
            continue
        Xtr, ytr, _, names = to_matrix(train_rows, sites)
        Xte, yte, yde, _ = to_matrix(test_rows, sites)
        model = LogisticModel(l2=l2, pos_weight=pos_weight).fit(Xtr, ytr)
        ptr = model.predict_proba(Xtr)
        tg, tr = best_thresholds(ptr, ytr)
        pte = model.predict_proba(Xte)
        for i, r in enumerate(test_rows):
            pooled_p.append(float(pte[i]))
            pooled_y.append(float(yte[i]))
            pooled_yd.append(float(yde[i]))
            pooled_col.append(proba_to_colour(pte[i], tg, tr))
            pooled_meta.append((r["site"], r["date"], r["ec"]))
    return pooled_p, pooled_y, pooled_yd, pooled_col, pooled_meta


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt(m):
    return (f"n={m['n']:>3}  GREEN={m['n_green']:>3} "
            f"(false-safe {m['green_unsafe']}={m['green_unsafe_pct']:.0f}%, "
            f"dang {m['green_dangerous']})  "
            f"RED={m['n_red']:>3} (unsafe {m['red_unsafe_pct']:.0f}%)  "
            f"sens={m['sensitivity_unsafe']*100:.0f}%  "
            f"clear-safe={m['specificity_green']*100:.0f}%  "
            f"cost={m['mean_cost']:.3f}")


def main():
    rows = build_dataset(api_k=0.85)
    n = len(rows)
    n_unsafe = int(sum(r["unsafe"] for r in rows))
    n_dang = int(sum(r["dangerous"] for r in rows))
    print(f"=== ThamesWatch red-team evaluation ===")
    print(f"{n} tests · {n_unsafe} unsafe (EC>500) · {n_dang} dangerous (EC>2000) · "
          f"base unsafe rate {n_unsafe/n*100:.0f}%\n")

    report = {}

    # --- In-sample reference: production v3 rules on full set ---
    v3 = v3_colours(rows)
    yall = [r["unsafe"] for r in rows]
    ydall = [r["dangerous"] for r in rows]
    m_v3 = colour_metrics(v3, yall, ydall)
    print("PRODUCTION v3 RULES  [IN-SAMPLE — optimistic, same rows used to tune]")
    print("  " + _fmt(m_v3) + "\n")
    report["v3_insample"] = m_v3

    # --- Forward-chaining (expanding window) OOS ---
    print("FORWARD-CHAINING (expanding window — operational, out-of-sample):")
    fc = {}
    for label, cls in [("persistence", PersistenceBaseline),
                       ("rain-threshold", RainThresholdBaseline),
                       ("base-rate", BaseRateBaseline)]:
        p, y, yd, col = forward_chaining_baseline(rows, cls)
        m = colour_metrics(col, y, yd)
        m["roc_auc"] = roc_auc(y, p); m["pr_auc"] = pr_auc(y, p); m["brier"] = brier(y, p)
        fc[label] = m
        print(f"  {label:16s} " + _fmt(m) +
              f"  AUC={m['roc_auc']:.2f} PR={m['pr_auc']:.2f} Brier={m['brier']:.3f}")

    p, y, yd, col, meta = forward_chaining_logistic(rows)
    m = colour_metrics(col, y, yd)
    m["roc_auc"] = roc_auc(y, p); m["pr_auc"] = pr_auc(y, p); m["brier"] = brier(y, p)
    fc["logistic"] = m
    print(f"  {'logistic (new)':16s} " + _fmt(m) +
          f"  AUC={m['roc_auc']:.2f} PR={m['pr_auc']:.2f} Brier={m['brier']:.3f}")
    report["forward_chaining"] = fc

    # The same OOS rows scored by the production rules, for a like-for-like cost compare.
    oos_meta_keys = {(s, d) for (s, d, e) in meta}
    oos_rows = [r for r in rows if (r["site"], r["date"]) in oos_meta_keys]
    v3_oos = v3_colours(oos_rows)
    m_v3_oos = colour_metrics(v3_oos, [r["unsafe"] for r in oos_rows],
                              [r["dangerous"] for r in oos_rows])
    print(f"  {'v3 rules (same OOS rows, still in-sample-tuned)':46s}\n    " + _fmt(m_v3_oos))
    report["v3_on_oos_rows"] = m_v3_oos

    # --- Leave-one-site-out ---
    print("\nLEAVE-ONE-SITE-OUT (geographic transfer):")
    p, y, yd, col, meta = leave_one_site_out_logistic(rows)
    m = colour_metrics(col, y, yd)
    m["roc_auc"] = roc_auc(y, p); m["pr_auc"] = pr_auc(y, p); m["brier"] = brier(y, p)
    print(f"  {'logistic (new)':16s} " + _fmt(m) +
          f"  AUC={m['roc_auc']:.2f} PR={m['pr_auc']:.2f} Brier={m['brier']:.3f}")
    report["leave_one_site_out_logistic"] = m

    # --- Full-data fit: coefficients (interpretability) ---
    X, yv, ydv, names = to_matrix(rows)
    full = LogisticModel(l2=2.0, pos_weight=3.0).fit(X, yv)
    print("\nFULL-DATA logistic — standardized coefficients (sign = direction of risk):")
    for name, coef in full.coef_report(names):
        print(f"  {name:26s} {coef:+.3f}")
    report["full_coefficients"] = {n: float(c) for n, c in full.coef_report(names)}

    import os
    from tw.paths import REPO_DIR
    out_path = os.path.join(REPO_DIR, "altmodel", "results.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
