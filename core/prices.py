"""Notowania dzienne OHLCV: Stooq, fallback Yahoo Finance; cache w SQLite."""
import io
import sqlite3
import time
from datetime import date

import pandas as pd
import requests

DB_PATH = "cache.db"
OHLCV = ["open", "high", "low", "close", "volume"]
_UA = {"User-Agent": "Mozilla/5.0"}
SOURCE_COOLDOWN_S = 600  # po awarii/blokadzie źródło jest pomijane, żeby nie czekać na timeouty przy każdym tickerze
_down_since: dict = {}


class SourceUnavailable(requests.RequestException):
    """Źródło nie zwraca danych (blokada, JS challenge)."""

# Końcówka tickera XTB -> końcówka Yahoo Finance (Stooq używa .pl/.us/.de/.uk wprost)
YAHOO_SUFFIX = {"PL": ".WA", "US": "", "DE": ".DE", "UK": ".L", "FR": ".PA", "NL": ".AS",
                "IT": ".MI", "ES": ".MC", "CH": ".SW", "CZ": ".PR", "HU": ".BD"}
# Indeksy: symbol roboczy -> (stooq, yahoo). Yahoo nie ma historii indeksów GPW (tylko 1 punkt),
# więc WIG20 = fundusz Beta ETF WIG20TR (total return, zamiennik indeksu).
INDEX_MAP = {"WIG20": ("wig20", "ETFBW20TR.WA"), "^SPX": ("^spx", "^GSPC"), "SPX": ("^spx", "^GSPC"), "^NDX": ("^ndx", "^NDX")}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (ticker TEXT, date TEXT, open REAL, high REAL, low REAL,
    close REAL, volume REAL, source TEXT, PRIMARY KEY (ticker, date));
CREATE TABLE IF NOT EXISTS prices_cover (ticker TEXT PRIMARY KEY, d_from TEXT, d_to TEXT, fetched TEXT);
"""


def to_source_symbol(ticker: str, source: str) -> str:
    """Ticker XTB ('PKN.PL', 'AAPL.US', 'EUNL.DE', 'WIG20') -> symbol Stooqa lub Yahoo."""
    t = ticker.strip().upper()
    if t in INDEX_MAP:
        return INDEX_MAP[t][0 if source == "stooq" else 1]
    base, _, suffix = t.rpartition(".")
    if not base:  # ticker bez końcówki traktujemy jak amerykański
        base, suffix = t, "US"
    if source == "stooq":
        return f"{base.lower()}" if suffix == "PL" else f"{base.lower()}.{suffix.lower()}"
    if source == "yahoo":
        return base + YAHOO_SUFFIX.get(suffix, f".{suffix}")
    raise ValueError(f"Nieznane źródło: {source}")


def _empty():
    return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], name="date"), dtype=float)


def fetch_stooq(ticker: str, start, end) -> pd.DataFrame:
    sym = to_source_symbol(ticker, "stooq")
    url = (f"https://stooq.com/q/d/l/?s={sym}&i=d&d1={pd.Timestamp(start):%Y%m%d}&d2={pd.Timestamp(end):%Y%m%d}")
    r = requests.get(url, headers=_UA, timeout=(4, 10))
    r.raise_for_status()
    text = r.text.lstrip()
    if text.startswith("<"):  # HTML / JS challenge zamiast CSV
        raise SourceUnavailable("Stooq zwrócił stronę HTML zamiast CSV")
    if not text.lower().startswith("date,"):  # 'No data'
        return _empty()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"]).rename(columns=str.lower)
    df = df.rename(columns={"date": "date"}).set_index("date").sort_index()
    for c in OHLCV:
        if c not in df:
            df[c] = float("nan")
    return df[OHLCV].astype(float)


def fetch_yahoo(ticker: str, start, end) -> pd.DataFrame:
    sym = to_source_symbol(ticker, "yahoo")
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"period1": p1, "period2": p2, "interval": "1d"}, headers=_UA, timeout=(4, 15))
    if r.status_code == 404:
        return _empty()
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result")
    if not res or "timestamp" not in res[0]:
        return _empty()
    q = res[0]["indicators"]["quote"][0]
    idx = pd.to_datetime(res[0]["timestamp"], unit="s", utc=True).tz_convert(res[0]["meta"].get("exchangeTimezoneName", "UTC"))
    df = pd.DataFrame({c: q.get(c) for c in OHLCV}, index=idx.tz_localize(None).normalize()).dropna(subset=["close"])
    df.index.name = "date"
    return df.astype(float)


def _conn(db_path):
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)
    return con


def get_prices(ticker: str, start, end, db_path=DB_PATH, fetchers=None) -> pd.DataFrame:
    """Dzienne OHLCV [start, end] z cache; brakujący zakres pobierany ze Stooq, potem Yahoo.

    Zwraca pusty DataFrame, gdy żadne źródło nie ma danych.
    """
    fetchers = fetchers or [("stooq", fetch_stooq), ("yahoo", fetch_yahoo)]
    ticker = ticker.upper()
    s, e = pd.Timestamp(start).normalize(), min(pd.Timestamp(end).normalize(), pd.Timestamp(date.today()))
    con = _conn(db_path)
    cov = con.execute("SELECT d_from, d_to, fetched FROM prices_cover WHERE ticker=?", (ticker,)).fetchone()
    # świeże, jeśli zakres pokryty i (dziś już pobierano lub zakres kończy się >5 dni temu)
    fresh = bool(cov) and pd.Timestamp(cov[0]) <= s and (
        pd.Timestamp(cov[1]) >= e or cov[2] == date.today().isoformat())
    if not fresh:
        lo = min(s, pd.Timestamp(cov[0])) if cov else s
        hi = max(e, pd.Timestamp(cov[1])) if cov else e
        for name, fn in fetchers:
            if time.time() - _down_since.get(name, 0) < SOURCE_COOLDOWN_S:
                continue
            try:
                df = fn(ticker, lo, hi)
            except requests.RequestException:
                _down_since[name] = time.time()
                continue
            if len(df):
                with con:
                    con.executemany(
                        "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?)",
                        [(ticker, i.date().isoformat(), *[None if pd.isna(r[c]) else r[c] for c in OHLCV], name)
                         for i, r in df.iterrows()])
                    con.execute("INSERT OR REPLACE INTO prices_cover VALUES (?,?,?,?)",
                                (ticker, lo.date().isoformat(), hi.date().isoformat(), date.today().isoformat()))
                break
    df = pd.read_sql("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
                     con, params=(ticker, s.date().isoformat(), e.date().isoformat()))
    con.close()
    out = df.set_index(pd.to_datetime(df.pop("date")))
    out.index.name = "date"
    return out
