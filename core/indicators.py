"""Wskaźniki analizy technicznej – czyste funkcje na pandas Series (bez TA-Lib)."""
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid, sd = s.rolling(n).mean(), s.rolling(n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def _wilder(x: pd.Series, n: int) -> pd.Series:
    """Wygładzanie Wildera: start = średnia z n pierwszych wartości, dalej (prev*(n-1)+x)/n."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    valid = np.flatnonzero(~np.isnan(v))
    if len(valid) >= n:
        i0 = valid[0] + n - 1
        out[i0] = v[valid[0]:i0 + 1].mean()
        for i in range(i0 + 1, len(v)):
            out[i] = (out[i - 1] * (n - 1) + v[i]) / n
    return pd.Series(out, index=x.index)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    ag, al = _wilder(d.clip(lower=0).where(d.notna()), n), _wilder((-d).clip(lower=0).where(d.notna()), n)
    out = 100 - 100 / (1 + ag / al.replace(0, np.nan))
    return out.where(al != 0, 100.0).where(ag.notna())


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3) -> pd.DataFrame:
    hh, ll = high.rolling(k).max(), low.rolling(k).min()
    pk = (close - ll) / (hh - ll).replace(0, np.nan) * 100
    return pd.DataFrame({"k": pk, "d": pk.rolling(d).mean()})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    pc = close.shift()
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = (high - low).iloc[0]
    return _wilder(tr, n)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def pivots(high: pd.Series, low: pd.Series, window: int = 5) -> tuple[pd.Series, pd.Series]:
    """Wsparcia i opory jako lokalne ekstrema (okno `window` świec z każdej strony).

    Zwraca (wsparcia, opory) – Series tylko z punktami zwrotnymi. Ostatnie `window` świec
    nie może być potwierdzone, więc nie zawiera pivotów.
    """
    w = 2 * window + 1
    res = high[high == high.rolling(w, center=True).max()].dropna()
    sup = low[low == low.rolling(w, center=True).min()].dropna()
    return sup, res


def cross_signals(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """+1 = golden cross (szybka przebija wolną od dołu), -1 = death cross, 0 = brak."""
    above = fast > slow
    below = fast < slow
    golden = above & ~above.shift(fill_value=False) & fast.shift().notna() & slow.shift().notna()
    death = below & ~below.shift(fill_value=False) & fast.shift().notna() & slow.shift().notna()
    return golden.astype(int) - death.astype(int)
