"""Pozycje, wycena, zyski i stopy zwrotu. Waluta bazowa: PLN.

Koszt zakupu/sprzedaży bierzemy z `kwota_pln` (faktyczna kwota rozliczona przez XTB w PLN);
kurs NBP z dnia poprzedniego (core.fx) służy do wyceny i do przeliczeń, gdy brak kwoty w PLN.
"""
import numpy as np
import pandas as pd

MARKET_BY_SUFFIX = {"PL": "GPW", "US": "USA", "DE": "Niemcy (Xetra)", "UK": "Wielka Brytania",
                    "FR": "Francja", "NL": "Holandia", "IT": "Włochy", "ES": "Hiszpania",
                    "CH": "Szwajcaria", "CZ": "Czechy", "HU": "Węgry"}
SIGN = {"kupno": 1, "sprzedaż": -1}
FLOW_TYPES = ["wpłata", "wypłata", "przelew_wewnętrzny"]  # zewnętrzne przepływy portfela


def market_of(ticker: str) -> str:
    return MARKET_BY_SUFFIX.get(str(ticker).rsplit(".", 1)[-1], "Inne")


def account_summary(data: dict) -> pd.DataFrame:
    """Per konto: pozycje (migawka raportu), gotówka, razem, wpłaty netto."""
    rep, op, cash, tr = data["reports"], data["open_positions"], data["cash_ops"], data["transactions"]
    rows = []
    for konto in rep["konto"]:
        c, t = cash[cash["konto"] == konto], tr[tr["konto"] == konto]
        gotowka = c["kwota"].sum() - (t["typ"].map(SIGN) * t["kwota_pln"]).sum()
        pozycje = op.loc[op["konto"] == konto, "wartość"].sum()
        rows.append({"konto": konto, "produkt": c["produkt"].iloc[0] if len(c) else "",
                     "pozycje": pozycje, "gotówka": gotowka, "razem": pozycje + gotowka,
                     "wpłaty_netto": c[c["typ"].isin(FLOW_TYPES)]["kwota"].sum(),
                     "zysk_pozycji": op.loc[op["konto"] == konto, "zysk"].sum()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- pozycje

def _all_positions(transactions: pd.DataFrame, price_pln: dict | pd.Series, names: dict | None = None) -> pd.DataFrame:
    """Wszystkie tickery z historii (także zamknięte, ilość 0), metodą średniego kosztu."""
    price_pln = dict(price_pln)
    rows = []
    for ticker, g in transactions.sort_values("data", kind="stable").groupby("ticker"):
        qty = cost_pln = cost_cur = realized = 0.0
        for r in g.itertuples():
            if r.typ == "kupno":
                qty += r.ilość
                cost_pln += r.kwota_pln + (r.prowizja or 0)
                cost_cur += r.ilość * r.cena
            elif qty > 0:  # sprzedaż: zdejmujemy proporcjonalną część kosztu
                share = min(r.ilość / qty, 1.0)
                realized += r.kwota_pln - (r.prowizja or 0) - cost_pln * share
                cost_pln -= cost_pln * share
                cost_cur -= cost_cur * share
                qty -= r.ilość
        if qty < 1e-9:
            qty = cost_pln = cost_cur = 0.0
        rows.append({"ticker": ticker, "nazwa": (names or {}).get(ticker, ticker), "waluta": g["waluta"].iloc[-1],
                     "ilość": qty, "śr_cena_zakupu": cost_cur / qty if qty else np.nan,
                     "koszt_pln": cost_pln, "cena_pln": price_pln.get(ticker, np.nan),
                     "zrealizowany_pln": realized})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["wartość_pln"] = df["ilość"] * df["cena_pln"]
    df["zysk_pln"] = df["wartość_pln"] - df["koszt_pln"]
    df["zysk_proc"] = np.where(df["koszt_pln"] > 0, df["zysk_pln"] / df["koszt_pln"] * 100, np.nan)
    return df


def positions(transactions: pd.DataFrame, price_pln: dict | pd.Series, names: dict | None = None) -> pd.DataFrame:
    """Pozycje otwarte metodą średniego kosztu.

    price_pln: bieżąca cena jednostki w PLN (ticker -> cena). Kolumny wyniku:
    ticker, nazwa, waluta, ilość, śr_cena_zakupu (w walucie instrumentu), koszt_pln,
    cena_pln, wartość_pln, zysk_pln, zysk_proc, udział, zrealizowany_pln, rynek.
    """
    df = _all_positions(transactions, price_pln, names)
    if df.empty:
        return df
    open_ = df[df["ilość"] > 0].copy()
    open_["udział"] = open_["wartość_pln"] / open_["wartość_pln"].sum() * 100
    open_["rynek"] = open_["ticker"].map(market_of)
    return open_.sort_values("wartość_pln", ascending=False).reset_index(drop=True)


def profit_breakdown(transactions: pd.DataFrame, price_pln: dict | pd.Series) -> dict:
    """Zysk z pozycji: niezrealizowany (otwarte), zrealizowany (wszystkie sprzedaże) i koszt otwartych."""
    df = _all_positions(transactions, price_pln)
    if df.empty:
        return {"niezrealizowany": 0.0, "zrealizowany": 0.0, "koszt_otwartych": 0.0, "niezrealizowany_proc": float("nan")}
    open_ = df[df["ilość"] > 0]
    cost = float(open_["koszt_pln"].sum())
    unreal = float(open_["zysk_pln"].sum())
    return {"niezrealizowany": unreal, "zrealizowany": float(df["zrealizowany_pln"].sum()), "koszt_otwartych": cost,
            "niezrealizowany_proc": unreal / cost * 100 if cost > 0 else float("nan")}


def snapshot_prices(open_positions: pd.DataFrame) -> dict:
    """Cena jednostki w PLN z migawki raportu XTB (wartość / ilość) – awaryjnie, gdy brak notowań."""
    g = open_positions.groupby("ticker").agg(w=("wartość", "sum"), q=("ilość", "sum"))
    return (g["w"] / g["q"]).to_dict()


# ---------------------------------------------------------------- wartość w czasie

def daily_values(transactions: pd.DataFrame, cash_ops: pd.DataFrame, close: dict, fx: dict,
                 start=None, end=None) -> pd.DataFrame:
    """Wartość portfela na każdy dzień kalendarzowy.

    close: ticker -> Series cen zamknięcia (waluta instrumentu); brak notowań -> ostatnia cena transakcji.
    fx: waluta -> Series kursu NBP do PLN (z ffill na dni wolne).
    Zwraca: pozycje, gotówka, wartość, przepływ (netto danego dnia), wpłaty_netto (narastająco).
    """
    days_all = pd.concat([transactions["data"], cash_ops["data"]])
    start = pd.Timestamp(start if start is not None else days_all.min()).normalize()
    end = pd.Timestamp(end if end is not None else pd.Timestamp.today()).normalize()
    days = pd.date_range(start, end)
    tr = transactions.assign(day=transactions["data"].dt.normalize())
    tr["sq"] = tr["typ"].map(SIGN) * tr["ilość"]
    tr["cash"] = -tr["typ"].map(SIGN) * tr["kwota_pln"]
    qty = tr.pivot_table(index="day", columns="ticker", values="sq", aggfunc="sum").reindex(days).fillna(0).cumsum()
    pozycje = pd.Series(0.0, index=days)
    for ticker in qty.columns:
        cur = tr.loc[tr["ticker"] == ticker, "waluta"].iloc[-1]
        last_trade = tr[tr["ticker"] == ticker].set_index("day")["cena"]
        last_trade = last_trade[~last_trade.index.duplicated(keep="last")].reindex(days).ffill()
        px = close.get(ticker, pd.Series(dtype=float))
        px = px.reindex(px.index.union(days)).ffill().reindex(days)
        px = px.fillna(last_trade)
        if cur in ("PLN", ""):
            rate = 1.0
        elif cur in fx:
            rate = fx[cur].reindex(fx[cur].index.union(days)).ffill().reindex(days).bfill()
        else:
            raise ValueError(f"Brak kursów NBP dla waluty {cur} ({ticker})")
        pozycje += (qty[ticker].clip(lower=0) * px * rate).fillna(0)
    c = cash_ops.assign(day=cash_ops["data"].dt.normalize())
    cash_delta = (c.groupby("day")["kwota"].sum().reindex(days, fill_value=0)
                  + tr.groupby("day")["cash"].sum().reindex(days, fill_value=0))
    flow = c[c["typ"].isin(FLOW_TYPES)].groupby("day")["kwota"].sum().reindex(days, fill_value=0)
    out = pd.DataFrame({"pozycje": pozycje, "gotówka": cash_delta.cumsum(), "przepływ": flow})
    out["wartość"] = out["pozycje"] + out["gotówka"]
    out["wpłaty_netto"] = out["przepływ"].cumsum()
    return out


# ---------------------------------------------------------------- stopy zwrotu

def _slice(daily: pd.DataFrame, start=None, end=None):
    """Zwraca (wartość początkowa = koniec dnia przed startem, wycinek)."""
    start = pd.Timestamp(start) if start is not None else daily.index[0]
    sub = daily.loc[start:end] if end is not None else daily.loc[start:]
    prev = daily.loc[:start - pd.Timedelta(days=1), "wartość"]
    return (float(prev.iloc[-1]) if len(prev) else 0.0), sub


def twr_series(daily: pd.DataFrame, start=None, end=None) -> pd.Series:
    """Skumulowana stopa TWR (indeks, start = 1.0). Przepływ liczony na koniec dnia."""
    v0, sub = _slice(daily, start, end)
    prev = pd.concat([pd.Series([v0]), sub["wartość"].iloc[:-1].reset_index(drop=True)]).values
    r = np.where(prev > 1e-9, (sub["wartość"].values - sub["przepływ"].values) / np.where(prev > 1e-9, prev, 1) - 1, 0.0)
    return pd.Series((1 + r).cumprod(), index=sub.index)


def twr(daily: pd.DataFrame, start=None, end=None) -> float:
    s = twr_series(daily, start, end)
    return float(s.iloc[-1] - 1) if len(s) else float("nan")


def xirr(flows: list, guess_range=(-0.9999, 1000.0)) -> float:
    """XIRR dla listy (data, kwota); wpłaty ujemne, wartość końcowa dodatnia. Bisekcja."""
    if not flows or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return float("nan")
    t0 = min(d for d, _ in flows)
    t = np.array([(pd.Timestamp(d) - pd.Timestamp(t0)).days / 365.0 for d, _ in flows])
    a = np.array([x for _, x in flows], dtype=float)
    f = lambda r: float(np.sum(a / (1 + r) ** t))
    lo, hi = guess_range
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def xirr_daily(daily: pd.DataFrame, start=None, end=None) -> float:
    """MWR/XIRR: wartość początkowa zakresu i wpłaty jako ujemne przepływy, wartość końcowa jako dodatnia."""
    v0, sub = _slice(daily, start, end)
    flows = []
    if v0 > 0:
        flows.append((sub.index[0] - pd.Timedelta(days=1), -v0))
    flows += [(d, -f) for d, f in sub["przepływ"].items() if abs(f) > 1e-12]
    flows.append((sub.index[-1], float(sub["wartość"].iloc[-1])))
    return xirr(flows)


# ---------------------------------------------------------------- podsumowanie

def summary(daily: pd.DataFrame, transactions: pd.DataFrame, cash_ops: pd.DataFrame, start=None, end=None) -> dict:
    """Wskaźniki portfela dla zakresu dat (domyślnie cała historia)."""
    v0, sub = _slice(daily, start, end)
    lo, hi = sub.index[0], sub.index[-1] + pd.Timedelta(days=1)
    c = cash_ops[(cash_ops["data"] >= lo) & (cash_ops["data"] < hi)]
    t = transactions[(transactions["data"] >= lo) & (transactions["data"] < hi)]
    flows = float(sub["przepływ"].sum())
    value = float(sub["wartość"].iloc[-1])
    profit = value - v0 - flows
    base = v0 + flows
    div = c[c["typ"] == "dywidenda"]["kwota"].sum()
    wht = c[c["typ"] == "podatek_u_źródła"]["kwota"].sum()
    return {
        "wartość": value, "wpłaty_netto": flows, "zysk": profit,
        "stopa_prosta": profit / base if base > 0 else float("nan"),
        "twr": twr(daily, start, end), "xirr": xirr_daily(daily, start, end),
        "dywidendy_brutto": float(div), "podatek_u_źródła": float(wht), "dywidendy_netto": float(div + wht),
        "odsetki_netto": float(c[c["typ"].isin(["odsetki", "podatek_od_odsetek"])]["kwota"].sum()),
        "prowizje": float(t["prowizja"].fillna(0).sum()),
    }
