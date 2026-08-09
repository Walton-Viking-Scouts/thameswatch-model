"""Models for the red-team harness — pure numpy/scipy.

  LogisticModel   — L2-penalized logistic regression with feature standardization
                    and optional class weighting (asymmetric cost). Outputs a
                    calibrated probability of "unsafe" (EC > 500).
  Baselines       — persistence, rainfall-threshold, base-rate. These are the honest
                    floor every real model must beat (USGS operational rule).

No scikit-learn: the optimizer is scipy.optimize.minimize (L-BFGS-B) on the
penalized negative log-likelihood, which is convex and tiny here (≤15 features,
≤239 rows).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_ridge_logistic(X, y, penalty, pos_weight=1.0):
    """Logistic regression with a per-column L2 penalty vector (bias unpenalized).

    X is used as-is (caller controls standardization). `penalty` is a length-d vector
    of ridge strengths, one per column of X — this is what makes partial pooling
    possible: shared slopes get a light penalty, site-specific deviations a heavy one.
    Returns w of length d+1 (w[0] is the bias).
    """
    n, d = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    pen = np.concatenate([[0.0], np.asarray(penalty, float)])  # bias unpenalized
    sw = np.where(y > 0.5, pos_weight, 1.0)

    def nll(w):
        p = _sigmoid(Xb @ w)
        eps = 1e-9
        ll = sw * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        return -np.sum(ll) + 0.5 * np.sum(pen * w * w)

    def grad(w):
        p = _sigmoid(Xb @ w)
        return Xb.T @ (sw * (p - y)) + pen * w

    res = minimize(nll, np.zeros(d + 1), jac=grad, method="L-BFGS-B")
    return res.x


class LogisticModel:
    """L2-penalized logistic regression with standardization + class weights."""

    def __init__(self, l2: float = 1.0, pos_weight: float = 1.0):
        self.l2 = l2
        self.pos_weight = pos_weight
        self.mu = None
        self.sd = None
        self.w = None  # includes bias as w[0]

    def _standardize(self, X, fit=False):
        if fit:
            self.mu = X.mean(axis=0)
            self.sd = X.std(axis=0)
            self.sd[self.sd < 1e-8] = 1.0  # leave one-hot/constant cols alone
        return (X - self.mu) / self.sd

    def fit(self, X, y):
        Xs = self._standardize(X, fit=True)
        n, d = Xs.shape
        Xb = np.hstack([np.ones((n, 1)), Xs])
        sample_w = np.where(y > 0.5, self.pos_weight, 1.0)

        def nll(w):
            z = Xb @ w
            p = _sigmoid(z)
            eps = 1e-9
            ll = sample_w * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
            # L2 on weights excluding bias
            reg = 0.5 * self.l2 * np.sum(w[1:] ** 2)
            return -np.sum(ll) + reg

        def grad(w):
            z = Xb @ w
            p = _sigmoid(z)
            g = Xb.T @ (sample_w * (p - y))
            g[1:] += self.l2 * w[1:]
            return g

        w0 = np.zeros(d + 1)
        res = minimize(nll, w0, jac=grad, method="L-BFGS-B")
        self.w = res.x
        return self

    def predict_proba(self, X):
        Xs = self._standardize(X, fit=False)
        Xb = np.hstack([np.ones((Xs.shape[0], 1)), Xs])
        return _sigmoid(Xb @ self.w)

    def coef_report(self, names):
        """Standardized coefficients (comparable magnitudes)."""
        return sorted(zip(names, self.w[1:]), key=lambda t: -abs(t[1]))


class PlattCalibrator:
    """1-D logistic recalibration of raw scores -> probabilities.

    Fit on a held-out fold's (score, label). Sigmoid (Platt) scaling, which the
    literature recommends over isotonic when positives are scarce.
    """

    def __init__(self):
        self.a = 1.0
        self.b = 0.0

    def fit(self, scores, y):
        s = np.asarray(scores, float)

        def nll(params):
            a, b = params
            p = _sigmoid(a * s + b)
            eps = 1e-9
            return -np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))

        res = minimize(nll, np.array([1.0, 0.0]), method="Nelder-Mead")
        self.a, self.b = res.x
        return self

    def transform(self, scores):
        return _sigmoid(self.a * np.asarray(scores, float) + self.b)


# ---------------------------------------------------------------------------
# Baselines — operate directly on feature-rows (dicts), not the matrix.
# ---------------------------------------------------------------------------

class PersistenceBaseline:
    """Predict from the site's most recent PRIOR test. p(unsafe)=1 if last EC>500.

    The honest floor: if a model can't beat "it was bad last time, assume it's still
    bad", it has no skill. Uses a small smoothing toward the site base rate when no
    prior test exists.
    """

    def __init__(self):
        self.history: dict[str, list[tuple[str, float]]] = {}
        self.base_rate = 0.4

    def fit(self, rows):
        self.history = {}
        ys = [r["unsafe"] for r in rows]
        self.base_rate = float(np.mean(ys)) if ys else 0.4
        for r in rows:
            self.history.setdefault(r["site"], []).append((r["date"], r["ec"]))
        for s in self.history:
            self.history[s].sort()
        return self

    def predict_proba_row(self, row):
        site = row["site"]
        date = row["date"]
        prior = [ec for (d, ec) in self.history.get(site, []) if d < date]
        if not prior:
            return self.base_rate
        return 1.0 if prior[-1] > 500 else 0.0


class RainThresholdBaseline:
    """p(unsafe) rises with rain_48h via a fitted logistic on that one feature."""

    def __init__(self):
        self.model = LogisticModel(l2=0.5)

    def fit(self, rows):
        X = np.array([[r["features"]["rain_48h"]] for r in rows])
        y = np.array([r["unsafe"] for r in rows])
        self.model.fit(X, y)
        return self

    def predict_proba_row(self, row):
        return float(self.model.predict_proba(
            np.array([[row["features"]["rain_48h"]]]))[0])


class BaseRateBaseline:
    """Per-site historical unsafe rate (climatology)."""

    def __init__(self):
        self.rates: dict[str, float] = {}
        self.overall = 0.4

    def fit(self, rows):
        from collections import defaultdict
        agg = defaultdict(list)
        for r in rows:
            agg[r["site"]].append(r["unsafe"])
        self.rates = {s: float(np.mean(v)) for s, v in agg.items()}
        self.overall = float(np.mean([r["unsafe"] for r in rows])) if rows else 0.4
        return self

    def predict_proba_row(self, row):
        return self.rates.get(row["site"], self.overall)
