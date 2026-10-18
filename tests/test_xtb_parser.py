import glob

import pytest

from core import portfolio, store
from core.xtb_parser import CASH_COLS, TRANSACTION_COLS, TYPE_MAP, parse_xtb

FILES = sorted(glob.glob("sample/*.xlsx"))
IKE = next(f for f in FILES if "IKE" in f)
PLN = next(f for f in FILES if "PLN" in f)


@pytest.fixture(scope="module")
def ike():
    return parse_xtb(IKE)


@pytest.fixture(scope="module")
def pln():
    return parse_xtb(PLN)


def test_columns(ike):
    assert set(TRANSACTION_COLS) <= set(ike.transactions.columns)
    assert set(CASH_COLS) <= set(ike.cash_ops.columns)
    assert len(ike.open_positions) == 6 and ike.konto == "55786676"


@pytest.mark.parametrize("fx", ["ike", "pln"])
def test_no_unknown_types_or_warnings(fx, request):
    exp = request.getfixturevalue(fx)
    assert [w for w in exp.warnings if "bez zakupu" not in w] == []  # spinoff to znany, opisany przypadek
    assert "nieznany" not in set(exp.cash_ops["typ"])
    assert set(exp.transactions["typ"]) <= {"kupno", "sprzedaż"}
    assert (exp.transactions["ilość"] > 0).all() and (exp.transactions["cena"] > 0).all()


def test_ticker_currency(ike):
    cur = dict(zip(ike.transactions["ticker"], ike.transactions["waluta"]))
    assert cur["AVGO.US"] == "USD" and cur["SXRV.DE"] == "EUR" and cur["XTB.PL"] == "PLN"


def test_cash_types_cover_domain(pln):
    assert {"wpłata", "dywidenda", "podatek_u_źródła", "odsetki", "przelew_wewnętrzny"} <= set(pln.cash_ops["typ"])


def test_type_map_values():
    assert all(t in ("transactions", "cash_ops") for t, _ in TYPE_MAP.values())


def test_partial_close_comment_parsed(pln):
    # 'CLOSE BUY 0.1711/4.7834 @ 361.40' -> ilość 0.1711, nie 4.7834
    s = pln.transactions
    kru = s[(s["ticker"] == "KRU.PL") & (s["typ"] == "sprzedaż")]
    assert 0.1711 in set(kru["ilość"])


def test_import_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    first = [store.import_file(f, db) for f in FILES]
    assert all(r["duplikaty"] == 0 for r in first)
    again = [store.import_file(f, db) for f in FILES]
    assert all(r["nowe_transakcje"] == 0 and r["nowe_operacje_gotówkowe"] == 0 for r in again)
    d = store.load_all(db)
    assert len(d["transactions"]) == sum(r["nowe_transakcje"] for r in first)


def test_portfolio_value(tmp_path):
    db = tmp_path / "t.db"
    for f in FILES:
        store.import_file(f, db)
    s = portfolio.account_summary(store.load_all(db)).set_index("produkt")
    assert s.loc["IKE", "pozycje"] == pytest.approx(27592.53)
    assert s.loc["My Trades", "pozycje"] == pytest.approx(14482.10)
    # gotówka = saldo operacji; po pełnej wycenie zostaje tylko drobna reszta
    assert s.loc["IKE", "gotówka"] == pytest.approx(2.58, abs=0.01)
    assert s.loc["My Trades", "gotówka"] == pytest.approx(0.88, abs=0.01)


def test_spinoff_gets_synthetic_zero_cost_buy(pln):
    # Syn2bio (S2B.PL) z wydzielenia SNT.PL: brak zakupu w Cash Operations, jest w Closed Positions
    t = pln.transactions
    buy = t[(t["ticker"] == "S2B.PL") & (t["typ"] == "kupno")]
    assert len(buy) == 1 and buy["kwota_pln"].iloc[0] == 0 and buy["ilość"].iloc[0] == 2
    assert any("S2B.PL" in w for w in pln.warnings)


def test_no_negative_holdings(ike, pln):
    for exp in (ike, pln):
        t = exp.transactions.assign(sq=lambda d: d["ilość"] * d["typ"].map({"kupno": 1, "sprzedaż": -1}))
        assert (t.sort_values("data").groupby("ticker")["sq"].cumsum() > -1e-9).all()
