"""Trwały magazyn SQLite: import plików bez duplikatów (klucz: konto + id operacji)."""
import sqlite3
from pathlib import Path

import pandas as pd

from core.xtb_parser import parse_xtb

DB_PATH = Path("cache.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    konto TEXT, id TEXT, data TEXT, ticker TEXT, typ TEXT, ilosc REAL, cena REAL,
    waluta TEXT, prowizja REAL, kwota_pln REAL, instrument TEXT, kategoria TEXT,
    produkt TEXT, position_id TEXT, PRIMARY KEY (konto, id));
CREATE TABLE IF NOT EXISTS cash_ops (
    konto TEXT, id TEXT, data TEXT, typ TEXT, kwota REAL, waluta TEXT, opis TEXT,
    ticker TEXT, produkt TEXT, PRIMARY KEY (konto, id));
CREATE TABLE IF NOT EXISTS open_positions (
    konto TEXT, produkt TEXT, ticker TEXT, nazwa TEXT, kategoria TEXT, ilosc REAL,
    wartosc REAL, cena_otwarcia REAL, zysk REAL, zysk_proc REAL, data_raportu TEXT);
CREATE TABLE IF NOT EXISTS reports (konto TEXT PRIMARY KEY, waluta TEXT, data_raportu TEXT);
"""

# kolumny z polskimi znakami -> nazwy w bazie
_DB = {"ilość": "ilosc", "wartość": "wartosc"}


def _conn(db_path):
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)
    return con


def _insert_new(con, table, df, cols) -> int:
    """INSERT OR IGNORE; zwraca liczbę faktycznie dodanych wierszy."""
    if df.empty:
        return 0
    d = df.rename(columns=_DB)
    d = d.assign(data=d["data"].astype(str))
    before = con.total_changes
    con.executemany(
        f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        d[cols].astype(object).where(d[cols].notna(), None).values.tolist(),
    )
    return con.total_changes - before


def import_file(src, db_path=DB_PATH) -> dict:
    """Wczytuje jeden eksport XTB. Powtórne wgranie tych samych operacji nic nie dubluje."""
    exp = parse_xtb(src)
    con = _conn(db_path)
    with con:
        n_tr = _insert_new(con, "transactions", exp.transactions, [
            "konto", "id", "data", "ticker", "typ", "ilosc", "cena", "waluta", "prowizja",
            "kwota_pln", "instrument", "kategoria", "produkt", "position_id"])
        n_cash = _insert_new(con, "cash_ops", exp.cash_ops, [
            "konto", "id", "data", "typ", "kwota", "waluta", "opis", "ticker", "produkt"])
        # Pozycje otwarte to migawka: obowiązuje tylko najnowszy raport danego konta.
        prev = con.execute("SELECT data_raportu FROM reports WHERE konto=?", (exp.konto,)).fetchone()
        newer = prev is None or str(exp.data_raportu) >= prev[0]
        if newer:
            con.execute("DELETE FROM open_positions WHERE konto=?", (exp.konto,))
            op = exp.open_positions.rename(columns=_DB).assign(data_raportu=str(exp.data_raportu))
            cols = ["konto", "produkt", "ticker", "nazwa", "kategoria", "ilosc", "wartosc",
                    "cena_otwarcia", "zysk", "zysk_proc", "data_raportu"]
            con.executemany(f"INSERT INTO open_positions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            op[cols].astype(object).where(op[cols].notna(), None).values.tolist())
            con.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)",
                        (exp.konto, exp.waluta, str(exp.data_raportu)))
    con.close()
    return {
        "konto": exp.konto, "nowe_transakcje": n_tr, "nowe_operacje_gotówkowe": n_cash,
        "duplikaty": len(exp.transactions) + len(exp.cash_ops) - n_tr - n_cash,
        "pozycje_zaktualizowane": newer, "ostrzeżenia": exp.warnings,
    }


def load_all(db_path=DB_PATH) -> dict:
    """Zwraca dict DataFrame'ów: transactions, cash_ops, open_positions, reports."""
    con = _conn(db_path)
    out = {t: pd.read_sql(f"SELECT * FROM {t}", con)
           for t in ("transactions", "cash_ops", "open_positions", "reports")}
    con.close()
    back = {v: k for k, v in _DB.items()}
    out["transactions"] = out["transactions"].rename(columns=back)
    out["open_positions"] = out["open_positions"].rename(columns=back)
    for t in ("transactions", "cash_ops"):
        out[t]["data"] = pd.to_datetime(out[t]["data"])
    return out


def reset(db_path=DB_PATH):
    """Czyści dane z importów (cache kursów i notowań zostaje)."""
    con = _conn(db_path)
    with con:
        for t in ("transactions", "cash_ops", "open_positions", "reports"):
            con.execute(f"DELETE FROM {t}")
    con.close()
