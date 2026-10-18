"""Import eksportu XTB (xlsx) -> ujednolicone DataFrame'y."""
import re
import warnings
from dataclasses import dataclass

import pandas as pd

# Typ operacji XTB (arkusz Cash Operations) -> (tabela, typ wewnętrzny).
# Nowy typ XTB dopisujesz tutaj, w jednym miejscu.
TYPE_MAP = {
    "Stock purchase": ("transactions", "kupno"),
    "Stock sell": ("transactions", "sprzedaż"),
    "Deposit": ("cash_ops", "wpłata"),
    "Withdrawal": ("cash_ops", "wypłata"),
    "Dividend": ("cash_ops", "dywidenda"),
    "Withholding tax": ("cash_ops", "podatek_u_źródła"),
    "Free funds interest": ("cash_ops", "odsetki"),
    "Free funds interest tax": ("cash_ops", "podatek_od_odsetek"),
    "IKE deposit": ("cash_ops", "przelew_wewnętrzny"),  # IKE <-> rachunek zwykły
    "Transfer": ("cash_ops", "przelew_wewnętrzny"),  # np. konwersja walut
}
UNKNOWN_TYPE = "nieznany"
SKIP_TYPES = {"Total"}  # wiersze podsumowań

# Końcówka tickera XTB -> waluta instrumentu
CURRENCY_BY_SUFFIX = {
    "PL": "PLN", "DE": "EUR", "FR": "EUR", "NL": "EUR", "IT": "EUR", "ES": "EUR",
    "US": "USD", "UK": "GBP", "CZ": "CZK", "HU": "HUF", "CH": "CHF",
}
DEFAULT_ACCOUNT_CURRENCY = "PLN"  # w eksporcie IKE pole waluty bywa puste

TRANSACTION_COLS = ["data", "ticker", "typ", "ilość", "cena", "waluta", "prowizja"]
CASH_COLS = ["data", "typ", "kwota", "waluta", "opis"]
OPEN_COLS = ["ticker", "nazwa", "kategoria", "ilość", "wartość", "cena_otwarcia", "zysk", "zysk_proc"]
META_COLS = ["konto", "produkt", "id"]

_TRADE_RE = re.compile(r"^(?:OPEN|CLOSE)\s+(?:BUY|SELL)\s+(?:[^\d\s]\S*\s+)?([\d.]+)(?:/[\d.]+)?\s*@\s*([\d.]+)")


@dataclass
class XtbExport:
    konto: str
    waluta: str
    data_raportu: pd.Timestamp
    transactions: pd.DataFrame
    cash_ops: pd.DataFrame
    open_positions: pd.DataFrame
    warnings: list


def _read(src, sheet, header=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(src, sheet_name=sheet, header=header)


def _table(raw: pd.DataFrame, first_col: str) -> pd.DataFrame:
    """Tabela zaczynająca się od wiersza z nagłówkiem first_col w kolumnie 0."""
    idx = raw.index[raw[0] == first_col][0]
    df = raw.iloc[idx + 1:].copy()
    df.columns = raw.iloc[idx]
    return df.dropna(how="all").reset_index(drop=True)


def _pid(x) -> str:
    """Position ID jako tekst bez '.0' (w arkuszach raz tekst, raz liczba)."""
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return str(x)


def _currency(ticker: str) -> str:
    suffix = str(ticker).rsplit(".", 1)[-1] if "." in str(ticker) else ""
    return CURRENCY_BY_SUFFIX.get(suffix, "")


def parse_xtb(src) -> XtbExport:
    """src: ścieżka lub obiekt plikowy (np. UploadedFile ze Streamlit)."""
    warns = []
    cash_raw = _read(src, "Cash Operations")
    konto = str(cash_raw.iloc[0, 1])

    # --- Open Positions: podsumowanie + pozycje zagregowane per ticker
    op_raw = _read(src, "Open Positions")
    data_raportu = pd.Timestamp(op_raw.iloc[2, 1])
    waluta = DEFAULT_ACCOUNT_CURRENCY
    for _, r in op_raw.iloc[3:8].iterrows():
        if r[1] == "Open position value" and isinstance(r[3], str) and r[3]:
            waluta = r[3]
    hdr = op_raw.index[(op_raw[0] == "Product") & (op_raw[1] == "Instrument/Position")][0]
    pos = op_raw.iloc[hdr + 1:].copy()
    pos.columns = op_raw.iloc[hdr]
    pos = pos.dropna(subset=["Product"])
    is_agg = pos["Type"].isna()
    agg, lots = pos[is_agg], pos[~is_agg]
    open_positions = pd.DataFrame({
        "ticker": agg["Ticker"].values,
        "nazwa": agg["Instrument/Position"].values,
        "kategoria": agg["Category"].values,
        "ilość": pd.to_numeric(agg["Volume"]).values,
        "wartość": pd.to_numeric(agg["Value"]).values,
        "cena_otwarcia": pd.to_numeric(agg["Open price"]).values,
        "zysk": pd.to_numeric(agg["Net Profit"]).values,
        "zysk_proc": pd.to_numeric(agg["Net Profit %"]).values,
    })
    open_positions["konto"] = konto
    open_positions["produkt"] = agg["Product"].values
    open_positions["data_raportu"] = data_raportu

    # --- Prowizje: otwarcie z Open Positions, zamknięcie z Closed Positions (po Position ID)
    comm = {}
    for pid, c in zip(lots["Instrument/Position"], pd.to_numeric(lots["Open Commission"]).fillna(0)):
        comm[_pid(pid)] = comm.get(_pid(pid), 0.0) + abs(c)
    closed = _table(_read(src, "Closed Positions"), "Instrument")
    closed = closed.dropna(subset=["Ticker"])  # bez wiersza 'Total'
    closed["pid"] = closed["Position ID"].map(_pid)
    for pid, c in zip(closed["pid"], pd.to_numeric(closed["Commission"]).fillna(0)):
        comm[pid] = comm.get(pid, 0.0) + abs(c)

    # --- Cash Operations
    cash = _table(cash_raw, "Type")
    cash = cash[~cash["Type"].isin(SKIP_TYPES)]
    unknown = sorted(set(cash["Type"]) - set(TYPE_MAP))
    if unknown:
        warns.append(f"Nieznane typy operacji (dopisz w TYPE_MAP): {unknown}")
    target = cash["Type"].map(lambda t: TYPE_MAP.get(t, ("cash_ops", UNKNOWN_TYPE)))
    cash["tabela"] = [t[0] for t in target]
    cash["typ"] = [t[1] for t in target]

    tr = cash[cash["tabela"] == "transactions"]
    rows, bad = [], []
    for _, r in tr.iterrows():
        m = _TRADE_RE.match(str(r["Comment"]))
        if not m:
            bad.append(r["Comment"])
            continue
        pid = _pid(r["Position ID"])
        rows.append({
            "data": r["Time"], "ticker": r["Ticker"], "typ": r["typ"],
            "ilość": float(m.group(1)), "cena": float(m.group(2)),
            "waluta": _currency(r["Ticker"]),
            "prowizja": comm.get(pid, 0.0),
            "kwota_pln": abs(float(r["Amount"])),
            "instrument": r["Instrument"], "kategoria": r["Category"],
            "konto": konto, "produkt": r["Product"], "id": str(r["ID"]),
            "position_id": pid,
        })
    if bad:
        warns.append(f"Nie rozpoznano {len(bad)} komentarzy transakcji, np. {bad[:2]}")
    # Pozycje bez zakupu w Cash Operations (np. spinoff: akcje otrzymane za 0) – dopisujemy zakup
    # z arkusza Closed Positions, żeby sprzedaż miała koszt (inaczej znika z zysku zrealizowanego).
    bought = {r["position_id"] for r in rows if r["typ"] == "kupno"}
    for pid, g in closed[~closed["pid"].isin(bought)].groupby("pid"):
        f = g.iloc[0]
        rows.append({
            "data": pd.Timestamp(f["Open Time (UTC)"]), "ticker": f["Ticker"], "typ": "kupno",
            "ilość": float(pd.to_numeric(g["Volume"]).sum()), "cena": float(f["Open Price"]),
            "waluta": _currency(f["Ticker"]), "prowizja": 0.0,
            "kwota_pln": float(pd.to_numeric(g["Purchase Value"]).sum()),
            "instrument": f["Instrument"], "kategoria": f["Category"], "konto": konto,
            "produkt": f["Product"], "id": f"pos-{pid}", "position_id": pid,
        })
        warns.append(f"Pozycja {pid} ({f['Ticker']}) bez zakupu w operacjach – dodano zakup z Closed Positions "
                     f"({f['Comment'] or 'brak komentarza'}).")
    transactions = pd.DataFrame(rows)

    co = cash[cash["tabela"] == "cash_ops"]
    cash_ops = pd.DataFrame({
        "data": co["Time"].values, "typ": co["typ"].values,
        "kwota": pd.to_numeric(co["Amount"]).values, "waluta": waluta,
        "opis": co["Comment"].fillna("").values,
        "ticker": co["Ticker"].fillna("").values,
        "konto": konto, "produkt": co["Product"].values, "id": co["ID"].astype(str).values,
    })

    for df in (transactions, cash_ops):
        if len(df):
            df["data"] = pd.to_datetime(df["data"])
    return XtbExport(konto, waluta, data_raportu, transactions, cash_ops, open_positions, warns)
