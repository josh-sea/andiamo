"""
Quant toolkit available inside the lab sandbox as `quant`.

Conventions: prices/returns are DataFrames indexed by date with one column per symbol.
Backtests trade weights computed at close t into the return from t to t+1 (no lookahead).
"""

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ---------- basics ----------

def returns(prices: pd.DataFrame, log: bool = False) -> pd.DataFrame:
    r = np.log(prices).diff() if log else prices.pct_change(fill_method=None)
    return r.iloc[1:]


def zscore(x, window: int = 20):
    return (x - x.rolling(window).mean()) / x.rolling(window).std()


def bollinger(close, window: int = 20, k: float = 2.0) -> dict:
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std()
    upper, lower = mid + k * sd, mid - k * sd
    return {"mid": mid, "upper": upper, "lower": lower,
            "pct_b": (close - lower) / (upper - lower), "bandwidth": (upper - lower) / mid}


def rsi(close, window: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def momentum(prices: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """Classic 12-1 momentum: return from t-lookback to t-skip."""
    return prices.shift(skip) / prices.shift(lookback) - 1


def realized_vol(rets, window: int = 21):
    return rets.rolling(window).std() * np.sqrt(TRADING_DAYS)


# ---------- regression & factors ----------

def ols(y: pd.Series, X, add_const: bool = True) -> dict:
    import statsmodels.api as sm
    X = pd.DataFrame(X)
    data = pd.concat([y.rename("_y"), X], axis=1).dropna()
    Xd = sm.add_constant(data[X.columns]) if add_const else data[X.columns]
    model = sm.OLS(data["_y"], Xd).fit()
    return {"params": model.params.to_dict(), "tvalues": model.tvalues.to_dict(),
            "pvalues": model.pvalues.to_dict(), "r2": model.rsquared, "adj_r2": model.rsquared_adj,
            "n": int(model.nobs), "resid": model.resid, "model": model}


def rolling_beta(y: pd.Series, x: pd.Series, window: int = 63) -> pd.Series:
    return y.rolling(window).cov(x) / x.rolling(window).var()


def factor_model(rets: pd.DataFrame, n_factors: int = 5) -> dict:
    """PCA statistical factor model. Returns loadings, factor returns, explained variance, residual returns."""
    from sklearn.decomposition import PCA
    clean = rets.dropna(axis=1, thresh=int(len(rets) * 0.9)).dropna()
    mu, sd = clean.mean(), clean.std()
    z = (clean - mu) / sd
    pca = PCA(n_components=n_factors).fit(z)
    factors = pd.DataFrame(pca.transform(z), index=z.index, columns=[f"F{i + 1}" for i in range(n_factors)])
    loadings = pd.DataFrame(pca.components_.T, index=z.columns, columns=factors.columns)
    resid = (z - factors @ loadings.T) * sd
    return {"loadings": loadings, "factors": factors,
            "explained_variance": pd.Series(pca.explained_variance_ratio_, index=factors.columns),
            "residuals": resid}


def index_decomposition(component_rets: pd.DataFrame, index_ret: pd.Series, alpha: float = 1e-5) -> pd.Series:
    """Lasso regression of index returns on component returns: which names drive the index."""
    from sklearn.linear_model import Lasso
    data = pd.concat([component_rets, index_ret.rename("_idx")], axis=1).dropna()
    model = Lasso(alpha=alpha, fit_intercept=True, max_iter=20000).fit(data.drop(columns="_idx"), data["_idx"])
    coefs = pd.Series(model.coef_, index=component_rets.columns)
    return coefs[coefs != 0].sort_values(key=abs, ascending=False)


def multi_regression(y: pd.Series, X: pd.DataFrame, window: int | None = None):
    """Full-sample OLS, or rolling coefficients if window is given."""
    if window is None:
        return ols(y, X)
    from statsmodels.regression.rolling import RollingOLS
    import statsmodels.api as sm
    data = pd.concat([y.rename("_y"), X], axis=1).dropna()
    return RollingOLS(data["_y"], sm.add_constant(data[X.columns]), window=window).fit().params


# ---------- relationships ----------

def lead_lag(x: pd.Series, y: pd.Series, max_lag: int = 10) -> pd.Series:
    """corr(x_t, y_{t+lag}). Positive lag with high corr means x leads y."""
    data = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    return pd.Series({lag: data["x"].corr(data["y"].shift(-lag)) for lag in range(-max_lag, max_lag + 1)})


def lead_lag_matrix(rets: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """corr(row_t, col_{t+lag}) for every pair: rows lead columns."""
    a = rets.iloc[:-lag] if lag else rets
    b = rets.shift(-lag).iloc[:-lag] if lag else rets
    az, bz = (a - a.mean()) / a.std(), (b - b.mean()) / b.std()
    return (az.T @ bz) / (len(a) - 1)


def granger(x: pd.Series, y: pd.Series, max_lag: int = 5) -> dict:
    """Does x Granger-cause y? Returns min p-value per lag (ssr F-test)."""
    import contextlib
    import io
    from statsmodels.tsa.stattools import grangercausalitytests
    data = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    with contextlib.redirect_stdout(io.StringIO()):
        res = grangercausalitytests(data[["y", "x"]], maxlag=max_lag)
    return {int(lag): float(r[0]["ssr_ftest"][1]) for lag, r in res.items()}


def half_life(spread: pd.Series) -> float:
    s = spread.dropna()
    lagged, delta = s.shift(1).iloc[1:], s.diff().iloc[1:]
    beta = np.polyfit(lagged, delta, 1)[0]
    return float(-np.log(2) / beta) if beta < 0 else float("inf")


def cointegration(a: pd.Series, b: pd.Series) -> dict:
    """Engle-Granger test. spread = a - hedge_ratio * b."""
    from statsmodels.tsa.stattools import coint
    data = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    _, pvalue, _ = coint(data["a"], data["b"])
    hedge = np.polyfit(data["b"], data["a"], 1)[0]
    spread = data["a"] - hedge * data["b"]
    return {"pvalue": float(pvalue), "hedge_ratio": float(hedge), "half_life": half_life(spread), "spread": spread}


def find_pairs(prices: pd.DataFrame, max_pvalue: float = 0.01, min_corr: float = 0.8) -> pd.DataFrame:
    """Scan all pairs (pre-filtered by return correlation) for cointegration."""
    rets = returns(prices).dropna(axis=1, thresh=int(len(prices) * 0.9))
    corr = rets.corr()
    cols = corr.columns
    out = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if corr.iat[i, j] >= min_corr:
                r = cointegration(prices[cols[i]], prices[cols[j]])
                if r["pvalue"] <= max_pvalue:
                    out.append({"a": cols[i], "b": cols[j], "corr": corr.iat[i, j], **{k: v for k, v in r.items() if k != "spread"}})
    return pd.DataFrame(out).sort_values("pvalue") if out else pd.DataFrame()


# ---------- frequency domain ----------

def spectrum(x: pd.Series, detrend: bool = True) -> pd.DataFrame:
    """FFT power spectrum. period is in observations (trading days for daily data)."""
    v = x.dropna().to_numpy(dtype=float)
    if detrend:
        v = v - np.polyval(np.polyfit(np.arange(len(v)), v, 1), np.arange(len(v)))
    power = np.abs(np.fft.rfft(v * np.hanning(len(v)))) ** 2
    freqs = np.fft.rfftfreq(len(v))
    df = pd.DataFrame({"freq": freqs[1:], "period": 1 / freqs[1:], "power": power[1:]})
    return df.sort_values("power", ascending=False)


def spectral_significance(x: pd.Series, n_surrogates: int = 200, seed: int = 0) -> pd.DataFrame:
    """Compare peak power to phase-shuffled surrogates; periodicities in prices are usually noise."""
    rng = np.random.default_rng(seed)
    v = x.dropna().to_numpy(dtype=float)
    v = v - v.mean()
    base = spectrum(pd.Series(v), detrend=False).set_index("period")["power"]
    fft = np.fft.rfft(v)
    peaks = []
    for _ in range(n_surrogates):
        phases = np.exp(2j * np.pi * rng.random(len(fft)))
        phases[0] = 1
        surrogate = np.fft.irfft(np.abs(fft) * phases, n=len(v))
        peaks.append(spectrum(pd.Series(surrogate), detrend=False)["power"].max())
    threshold = float(np.quantile(peaks, 0.95))
    top = base.sort_values(ascending=False).head(10).to_frame()
    top["significant_95"] = top["power"] > threshold
    return top


# ---------- events & sentiment ----------

def event_study(rets: pd.DataFrame, events: list, window: tuple = (-5, 10), benchmark: str | None = "SPY") -> dict:
    """events: list of (date, symbol[, sign]). Returns mean cumulative abnormal return path and t-stats.
    sign (+1/-1) flips bearish events so they can be pooled with bullish ones."""
    abn = rets.sub(rets[benchmark], axis=0) if benchmark and benchmark in rets else rets
    idx = abn.index
    paths = []
    for ev in events:
        date, sym = pd.Timestamp(ev[0]), ev[1]
        sign = ev[2] if len(ev) > 2 else 1
        if sym not in abn:
            continue
        pos = idx.searchsorted(date)
        lo, hi = pos + window[0], pos + window[1]
        if lo < 0 or hi >= len(idx):
            continue
        paths.append(abn[sym].iloc[lo:hi + 1].to_numpy() * sign)
    if not paths:
        return {"n": 0}
    arr = np.nan_to_num(np.array(paths))
    car = arr.cumsum(axis=1)
    offsets = list(range(window[0], window[1] + 1))
    mean = car.mean(axis=0)
    se = car.std(axis=0, ddof=1) / np.sqrt(len(car)) if len(car) > 1 else np.full(len(mean), np.nan)
    return {"n": len(car), "car": pd.Series(mean, index=offsets), "t_stat": pd.Series(mean / se, index=offsets)}


# ---------- backtesting ----------

def normalize_weights(w: pd.DataFrame, gross: float = 1.0) -> pd.DataFrame:
    w = w.fillna(0.0)
    total = w.abs().sum(axis=1)
    scale = (gross / total).where(total > gross, 1.0)
    return w.mul(scale, axis=0)


def perf_stats(pnl: pd.Series) -> dict:
    pnl = pnl.dropna()
    if len(pnl) < 2 or pnl.std() == 0:
        return {"days": len(pnl), "sharpe": 0.0, "ann_return": 0.0, "ann_vol": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0}
    equity = (1 + pnl).cumprod()
    return {
        "days": int(len(pnl)),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(TRADING_DAYS)),
        "ann_return": float(equity.iloc[-1] ** (TRADING_DAYS / len(pnl)) - 1),
        "ann_vol": float(pnl.std() * np.sqrt(TRADING_DAYS)),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "hit_rate": float((pnl > 0).mean()),
    }


def backtest(weights: pd.DataFrame, prices: pd.DataFrame, cost_bps: float = 5.0) -> dict:
    """Weights decided at close t earn returns from t to t+1. Costs charged on turnover."""
    w = normalize_weights(weights.reindex(prices.index).ffill())
    rets = prices.pct_change(fill_method=None).fillna(0.0)
    gross = (w.shift(1) * rets).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1).fillna(w.abs().sum(axis=1))
    pnl = gross - turnover * cost_bps / 1e4
    stats = perf_stats(pnl.iloc[1:])
    stats["avg_turnover"] = float(turnover.mean())
    stats["avg_gross"] = float(w.abs().sum(axis=1).mean())
    return {"pnl": pnl, "equity": (1 + pnl).cumprod(), "stats": stats}
