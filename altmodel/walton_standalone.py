"""Does Walton Wharf do better as a standalone model than inside the pooled one?

Walton has 109/239 tests — by far the most — so it is the one site with enough data to
support site-specific *slopes* (not just a site-specific intercept, which is all the
pooled model's site dummies provide). A pooled model forces one shared rain/CSO/flow
slope across all sites; the production model itself says flow acts oppositely at Walton
(higher flow -> more Wey contamination) vs Teddington (higher flow -> dilution), which a
single shared slope cannot represent.

This compares, on Walton's OOS rows only:
  - the pooled logistic (shared slopes + Walton dummy)        [from evaluate.py]
  - a Walton-ONLY logistic (its own slopes, fit on Walton)
  - the production v3 rules (in-sample reference)

Run:  python3 -m altmodel.walton_standalone
"""
from __future__ import annotations

import numpy as np

from altmodel.features import build_dataset, to_matrix, CONT_FEATURES
from altmodel.models import LogisticModel
from altmodel.evaluate import (
    forward_chaining_logistic, colour_metrics, roc_auc, pr_auc, brier,
    best_thresholds, proba_to_colour, v3_colours,
)

SITE = "Walton Wharf"


def walton_only_forward_chaining(rows, l2=1.0, pos_weight=3.0, warmup_frac=0.4, n_blocks=5):
    """Forward-chaining on Walton rows alone, with Walton-specific slopes.

    No site dummies (single site); the continuous features carry everything. l2 is a
    touch lighter than the pooled model since there are fewer, more-relevant rows.
    """
    wrows = [r for r in rows if r["site"] == SITE]
    dates = sorted({r["date"] for r in wrows})
    n = len(dates)
    warm = int(n * warmup_frac)
    bounds = [warm + int((n - warm) * b / n_blocks) for b in range(n_blocks + 1)]
    P, Y, YD, COL = [], [], [], []
    for b in range(n_blocks):
        cut = dates[bounds[b]] if bounds[b] < n else dates[-1]
        tdates = set(dates[bounds[b]:bounds[b + 1]])
        tr = [r for r in wrows if r["date"] < cut]
        te = [r for r in wrows if r["date"] in tdates]
        if not tr or not te:
            continue
        Xtr, ytr, _, _ = to_matrix(tr, sites=[SITE])
        Xte, yte, yde, _ = to_matrix(te, sites=[SITE])
        m = LogisticModel(l2=l2, pos_weight=pos_weight).fit(Xtr, ytr)
        ptr = m.predict_proba(Xtr)
        tg, trd = best_thresholds(ptr, ytr)
        pte = m.predict_proba(Xte)
        for i in range(len(te)):
            P.append(float(pte[i])); Y.append(float(yte[i])); YD.append(float(yde[i]))
            COL.append(proba_to_colour(pte[i], tg, trd))
    return P, Y, YD, COL


def _line(label, P, Y, YD, COL):
    m = colour_metrics(COL, Y, YD)
    auc = roc_auc(Y, P) if len(set(Y)) > 1 else float("nan")
    print(f"  {label:34s} n={m['n']:>3} GREEN={m['n_green']:>3} "
          f"(false-safe {m['green_unsafe']}={m['green_unsafe_pct']:.0f}%, dang {m['green_dangerous']}) "
          f"sens={m['sensitivity_unsafe']*100:.0f}% cost={m['mean_cost']:.3f} AUC={auc:.2f}")
    return m


def main():
    rows = build_dataset(api_k=0.85)
    wrows = [r for r in rows if r["site"] == SITE]
    nu = int(sum(r["unsafe"] for r in wrows))
    print(f"=== Walton Wharf standalone vs pooled ===")
    print(f"{len(wrows)} Walton tests · {nu} unsafe ({nu/len(wrows)*100:.0f}%)\n")

    print("OUT-OF-SAMPLE (forward-chaining), Walton rows only:")

    # Pooled model, sliced to Walton OOS rows
    P, Y, YD, COL, meta = forward_chaining_logistic(rows, l2=2.0, pos_weight=3.0)
    keep = [i for i, (s, d, e) in enumerate(meta) if s == SITE]
    Pp = [P[i] for i in keep]; Yp = [Y[i] for i in keep]
    YDp = [YD[i] for i in keep]; COLp = [COL[i] for i in keep]
    _line("pooled (shared slopes + dummy)", Pp, Yp, YDp, COLp)

    # Walton-only model
    Pw, Yw, YDw, COLw = walton_only_forward_chaining(rows)
    _line("Walton-only (own slopes)", Pw, Yw, YDw, COLw)

    # Production v3 on the SAME Walton OOS rows (in-sample-tuned reference)
    oos_keys = {(meta[i][1]) for i in keep}  # Walton OOS dates
    w_oos = [r for r in wrows if r["date"] in oos_keys]
    v3 = v3_colours(w_oos)
    _line("v3 rules (in-sample ref)",
          [0]*len(w_oos), [r["unsafe"] for r in w_oos],
          [r["dangerous"] for r in w_oos], v3)

    # Coefficients: pooled (Walton-relevant) vs Walton-only
    print("\nWHAT EACH MODEL LEARNS (standardized coefficients):")
    X, y, _, names = to_matrix(rows)
    pooled = LogisticModel(l2=2.0, pos_weight=3.0).fit(X, y)
    pooled_co = dict(pooled.coef_report(names))
    Xw, yw, _, wnames = to_matrix(wrows, sites=[SITE])
    wonly = LogisticModel(l2=1.0, pos_weight=3.0).fit(Xw, yw)
    wonly_co = dict(wonly.coef_report(wnames))
    print(f"  {'feature':14s} {'pooled':>10s} {'Walton-only':>12s}")
    for f in CONT_FEATURES:
        print(f"  {f:14s} {pooled_co.get(f,0):>+10.3f} {wonly_co.get(f,0):>+12.3f}")

    print("\nNote: small OOS n (Walton ~65 points, ~20 unsafe) — differences of a few")
    print("cases are within noise; read the coefficient *signs/sizes*, not 2nd-decimal AUC.")


if __name__ == "__main__":
    main()
