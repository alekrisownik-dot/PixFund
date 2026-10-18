"""Kursy średnie NBP (tabela A) z cache w SQLite."""
import sqlite3
from datetime import date, timedelta

import pandas as pd
import requests

DB_PATH = "cache.db"
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json"
MAX_SPAN_DAYS = 360  # limit API to 367 dni na zapytanie
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_rates (code TEXT, date TEXT, mid REAL, PRIMARY KEY (code, date));
CREATE TABLE IF NOT EXISTS fx_cover (code TEXT PRIMARY KEY, d_from TEXT, d_to TEXT);
"""


def _fetch_nbp(code: str, start: date, end: date) -> pd.Series:
    """Pobiera kursy z API NBP; 404 = brak notowań w przedziale (np. same święta)."""
    out = {}
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=MAX_SPAN_DAYS), end)
        r = requests.get(NBP_URL.format(code=code.lower(), start=cur, end=chunk_end), timeout=20)
        if r.status_code != 404:
            r.raise_for_status()
            out.update({pd.Timestamp(x["effectiveDate"]): x["mid"] for x in r.json()["rates"]})
        cur = chunk_end + timedelta(days=1)
    return pd.Series(out, dtype=float).sort_index()


def _conn(db_path):
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)
    return con


def get_rates(code: str, start, end, db_path=DB_PATH, fetcher=_fetch_nbp) -> pd.Series:
    """Kursy NBP dni roboczych z przedziału [start, end] (Series indeksowany datą).

    Pobiera z sieci tylko brakujący zakres. Zakres wstecz poszerzony o 10 dni, żeby
    kurs 'z dnia poprzedzającego' istniał także dla pierwszych dni po weekendzie/świętach.
    """
    code = code.upper()
    if code == "PLN":
        return pd.Series(1.0, index=pd.date_range(start, end))
    s, e = pd.Timestamp(start).date() - timedelta(days=10), min(pd.Timestamp(end).date(), date.today())
    con = _conn(db_path)
    cov = con.execute("SELECT d_from, d_to FROM fx_cover WHERE code=?", (code,)).fetchone()
    need = [(s, e)]
    if cov:
        c_from, c_to = date.fromisoformat(cov[0]), date.fromisoformat(cov[1])
        need = []
        if s < c_from:
            need.append((s, c_from - timedelta(days=1)))
        if e > c_to:
            need.append((c_to + timedelta(days=1), e))
    with con:
        for a, b in need:
            for ts, mid in fetcher(code, a, b).items():
                con.execute("INSERT OR REPLACE INTO fx_rates VALUES (?,?,?)", (code, ts.date().isoformat(), mid))
        if need:
            lo = min([s] + ([date.fromisoformat(cov[0])] if cov else []))
            hi = max([e] + ([date.fromisoformat(cov[1])] if cov else []))
            con.execute("INSERT OR REPLACE INTO fx_cover VALUES (?,?,?)", (code, lo.isoformat(), hi.isoformat()))
    df = pd.read_sql("SELECT date, mid FROM fx_rates WHERE code=? AND date>=? AND date<=? ORDER BY date",
                     con, params=(code, s.isoformat(), e.isoformat()))
    con.close()
    return pd.Series(df["mid"].values, index=pd.to_datetime(df["date"]), dtype=float)


def rate_on(rates: pd.Series, day, previous_day: bool = False) -> float:
    """Ostatni dostępny kurs na dzień `day` (weekendy/święta -> kurs z poprzedniego dnia roboczego).

    previous_day=True: kurs z dnia roboczego ściśle PRZED `day` (zasada przeliczania transakcji).
    """
    day = pd.Timestamp(day).normalize()
    sel = rates[rates.index < day] if previous_day else rates[rates.index <= day]
    if sel.empty:
        raise KeyError(f"Brak kursu NBP przed {day.date()}")
    return float(sel.iloc[-1])


def daily_rates(rates: pd.Series, start, end) -> pd.Series:
    """Kurs na każdy dzień kalendarzowy (weekendy/święta = ostatni dostępny)."""
    idx = pd.date_range(start, end)
    return rates.reindex(rates.index.union(idx)).ffill().reindex(idx)
