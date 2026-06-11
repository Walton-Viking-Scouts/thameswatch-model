"""Partial-pooling logistic — the middle ground between one shared model and per-site models.

Each site's effective slope for feature j is:   beta_j(site) = beta_j_shared + delta_j(site)
We fit the shared slopes with a light ridge penalty and the per-site deviations delta with
a HEAVY ridge penalty. As the deviation penalty -> infinity the deltas vanish and this is
exactly the pooled model; as it relaxes, a site (Walton, with the most data) earns its own
slope where the data supports it, while data-poor sites (Chertsey n=15) stay shrunk to the
shared estimate. This is ridge-regression's view of a hierarchical/mixed model — achievable
in pure numpy/scipy, no PyMC/sklearn.

Design matrix per row:
  [ standardized continuous features (shared) | site dummies | site x feature interactions ]
Penalty vector:
  [ l2_shared on each shared slope | l2_site on each dummy | l2_interact on each interaction ]

Run:  python3 -m altmodel.partial_pool
"""
from __future__ import annotations

import numpy as np

from altmodel.features import build_dataset, CONT_FEATURES, SITES_ORDERED
from altmodel.models import fit_ridge_logistic, LogisticModel
from altmodel.evaluate import (
    forward_chaining_logistic, colour_metrics, roc_auc, pr_auc,
    best_thresholds, proba_to_colour,
)

SITES = SITES_ORDERED
N_CONT = len(CONT_FEATURES)
N_SITE = len(SITES)
SITE_IDX = {s: i for i, s in enumerate(SITES)}


def _raw_blocks(rows):
    """Return raw continuous matrix, dummy matrix, and labels for a set of rows."""
    n = len(rows)
    C = np.zeros((n, N_CONT))
    D = np.zeros((n, N_SITE))
    y = np.zeros(n)
    yd = np.zeros(n)
    for i, r in enumerate(rows):
        f = r["features"]
        for j, name in enumerate(CONT_FEATURES):
            C[i, j] = f[name]
        si = SITE_IDX.get(r["site"])
        if si is not None:
            D[i, si] = 1.0
        y[i] = r["unsafe"]
        yd[i] = r["dangerous"]
    return C, D, y, yd


def _design(C, D, mu, sd):
    """Standardize continuous (with given mu/sd), build [cont | dummies | interactions]."""
    Z = (C - mu) / sd
    n = Z.shape[0]
    inter = np.zeros((n, N_CONT * N_SITE))
    for s in range(N_SITE):
        inter[:, s * N_CONT:(s + 1) * N_CONT] = Z * D[:, s:s + 1]
    return np.hstack([Z, D, inter])


def _penalty(l2_shared, l2_site, l2_interact):
    return np.concatenate([
        np.full(N_CONT, l2_shared),
        np.full(N_SITE, l2_site),
        np.full(N_CONT * N_SITE, l2_interact),
    ])


def forward_chaining_partial(rows, l2_shared=2.0, l2_site=1.0, l2_interact=20.0,
                             pos_weight=3.0, warmup_frac=0.4, n_blocks=5):
    dates = sorted({r["date"] for r in rows})
    n = len(dates); warm = int(n * warmup_frac)
    bounds = [warm + int((n - warm) * b / n_blocks) for b in range(n_blocks + 1)]
    pen = _penalty(l2_shared, l2_site, l2_interact)
    P, Y, YD, COL, META = [], [], [], [], []
    for b in range(n_blocks):
        cut = dates[bounds[b]] if bounds[b] < n else dates[-1]
        tdates = set(dates[bounds[b]:bounds[b + 1]])
        tr = [r for r in rows if r["date"] < cut]
        te = [r for r in rows if r["date"] in tdates]
        if not tr or not te:
            continue
        Ctr, Dtr, ytr, _ = _raw_blocks(tr)
        Cte, Dte, yte, yde = _raw_blocks(te)
        mu = Ctr.mean(axis=0); sd = Ctr.std(axis=0); sd[sd < 1e-8] = 1.0
        Xtr = _design(Ctr, Dtr, mu, sd)
        Xte = _design(Cte, Dte, mu, sd)
        w = fit_ridge_logistic(Xtr, ytr, pen, pos_weight=pos_weight)
        ptr = _predict(Xtr, w)
        tg, trd = best_thresholds(ptr, ytr)
        pte = _predict(Xte, w)
        for i, r in enumerate(te):
            P.append(float(pte[i])); Y.append(float(yte[i])); YD.append(float(yde[i]))
            COL.append(proba_to_colour(pte[i], tg, trd))
            META.append((r["site"], r["date"], r["ec"]))
    return P, Y, YD, COL, META


def _predict(X, w):
    z = np.hstack([np.ones((X.shape[0], 1)), X]) @ w
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def _slice(P, Y, YD, COL, META, site):
    idx = [i for i, m in enumerate(META) if m[0] == site]
    return ([P[i] for i in idx], [Y[i] for i in idx],
            [YD[i] for i in idx], [COL[i] for i in idx])


def _line(label, P, Y, YD, COL):
    m = colour_metrics(COL, Y, YD)
    auc = roc_auc(Y, P) if len(set(Y)) > 1 else float("nan")
    print(f"  {label:38s} n={m['n']:>3} GREEN={m['n_green']:>3} "
          f"(false-safe {m['green_unsafe']}={m['green_unsafe_pct']:.0f}%, dang {m['green_dangerous']}) "
          f"sens={m['sensitivity_unsafe']*100:.0f}% cost={m['mean_cost']:.3f} AUC={auc:.2f}")


def main():
    rows = build_dataset(api_k=0.85)

    print("=== Partial-pooling sweep: how much site-specific slope to allow ===")
    print("    l2_interact = inf  -> pooled (no site slopes);  small -> per-site slopes\n")
    print("OVERALL (all sites, forward-chaining OOS):")
    # pooled reference (the original alt model)
    P, Y, YD, COL, META = forward_chaining_logistic(rows, l2=2.0, pos_weight=3.0)
    _line("pooled (shared slopes only)", P, Y, YD, COL)
    pooled_walton = _slice(P, Y, YD, COL, META, "Walton Wharf")

    configs = [
        ("partial l2_interact=50 (firm)", 50.0),
        ("partial l2_interact=20 (medium)", 20.0),
        ("partial l2_interact=8  (loose)", 8.0),
    ]
    walton_slices = {}
    for label, li in configs:
        P, Y, YD, COL, META = forward_chaining_partial(rows, l2_interact=li)
        _line(label, P, Y, YD, COL)
        walton_slices[label] = _slice(P, Y, YD, COL, META, "Walton Wharf")

    print("\nWALTON WHARF slice only (the site with enough data to earn its own slopes):")
    _line("pooled", *pooled_walton)
    for label, li in configs:
        _line(label, *walton_slices[label])

    # What did partial pooling let Walton's flow slope become? (full-data fit, medium)
    print("\nWalton's site-specific deviations (full-data fit, l2_interact=20):")
    C, D, y, _ = _raw_blocks(rows)
    mu = C.mean(axis=0); sd = C.std(axis=0); sd[sd < 1e-8] = 1.0
    X = _design(C, D, mu, sd)
    w = fit_ridge_logistic(X, y, _penalty(2.0, 1.0, 20.0), pos_weight=3.0)
    shared = w[1:1 + N_CONT]
    wi = SITE_IDX["Walton Wharf"]
    inter_start = 1 + N_CONT + N_SITE + wi * N_CONT
    walt_delta = w[inter_start:inter_start + N_CONT]
    print(f"  {'feature':12s} {'shared':>9s} {'Walton dev':>11s} {'Walton eff':>11s}")
    for j, name in enumerate(CONT_FEATURES):
        print(f"  {name:12s} {shared[j]:>+9.3f} {walt_delta[j]:>+11.3f} {shared[j]+walt_delta[j]:>+11.3f}")


if __name__ == "__main__":
    main()
