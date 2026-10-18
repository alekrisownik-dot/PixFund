import pandas as pd
import pytest

from core import portfolio as pf


def tr(rows):
    df = pd.DataFrame(rows, columns=["data", "ticker", "typ", "ilość", "cena", "waluta", "prowizja", "kwota_pln"])
    df["data"] = pd.to_datetime(df["data"])
    return df


def cash(rows):
    df = pd.DataFrame(rows, columns=["data", "typ", "kwota"])
    df["data"] = pd.to_datetime(df["data"])
    return df


def test_positions_average_cost_and_realized():
    t = tr([("2024-01-01", "A.PL", "kupno", 10, 10, "PLN", 0, 100),
            ("2024-01-02", "A.PL", "kupno", 10, 20, "PLN", 0, 200),
            ("2024-01-03", "A.PL", "sprzedaż", 5, 30, "PLN", 0, 150)])
    p = pf.positions(t, {"A.PL": 30.0}).iloc[0]
    assert p["ilość"] == 15 and p["śr_cena_zakupu"] == pytest.approx(15)
    assert p["koszt_pln"] == pytest.approx(225) and p["zrealizowany_pln"] == pytest.approx(75)
    assert p["wartość_pln"] == 450 and p["zysk_pln"] == pytest.approx(225) and p["zysk_proc"] == pytest.approx(100)
    assert p["udział"] == pytest.approx(100) and p["rynek"] == "GPW"


def test_positions_share_and_closed_position_hidden():
    t = tr([("2024-01-01", "A.PL", "kupno", 1, 100, "PLN", 0, 100),
            ("2024-01-01", "B.US", "kupno", 1, 25, "USD", 0, 100),
            ("2024-01-02", "C.PL", "kupno", 1, 5, "PLN", 0, 5),
            ("2024-01-03", "C.PL", "sprzedaż", 1, 6, "PLN", 0, 6)])
    p = pf.positions(t, {"A.PL": 300.0, "B.US": 100.0, "C.PL": 6.0})
    assert list(p["ticker"]) == ["A.PL", "B.US"]
    assert list(p["udział"]) == pytest.approx([75, 25])


def test_commission_in_cost():
    t = tr([("2024-01-01", "A.PL", "kupno", 1, 100, "PLN", 2, 100)])
    assert pf.positions(t, {"A.PL": 100.0}).iloc[0]["koszt_pln"] == 102


def test_daily_values_pln_and_fx():
    t = tr([("2024-01-01 10:00", "A.PL", "kupno", 10, 10, "PLN", 0, 100),
            ("2024-01-02 10:00", "B.US", "kupno", 1, 5, "USD", 0, 20)])
    c = cash([("2024-01-01 09:00", "wpłata", 1000)])
    days = pd.date_range("2024-01-01", "2024-01-03")
    close = {"A.PL": pd.Series([10.0, 11.0, 12.0], index=days), "B.US": pd.Series([5.0, 5.0, 6.0], index=days)}
    d = pf.daily_values(t, c, close, {"USD": pd.Series(4.0, index=days)}, "2024-01-01", "2024-01-03")
    assert list(d["gotówka"]) == [900, 880, 880]
    assert list(d["pozycje"]) == [100, 110 + 20, 120 + 24]
    assert list(d["wartość"]) == [1000, 1010, 1024]
    s = pf.summary(d, t, c)
    assert s["wpłaty_netto"] == 1000 and s["zysk"] == pytest.approx(24) and s["stopa_prosta"] == pytest.approx(0.024)


def test_daily_values_falls_back_to_trade_price_without_quotes():
    t = tr([("2024-01-01", "A.PL", "kupno", 2, 7, "PLN", 0, 14)])
    d = pf.daily_values(t, cash([("2024-01-01", "wpłata", 14)]), {}, {}, "2024-01-01", "2024-01-02")
    assert list(d["pozycje"]) == [14, 14]


def test_twr_hand_calculated():
    # dzień0: wpłata 100; dzień1: 110 (+10%); dzień2: wpłata 100, wartość 210 (0%); dzień3: 231 (+10%)
    idx = pd.date_range("2024-01-01", periods=4)
    d = pd.DataFrame({"wartość": [100, 110, 210, 231.0], "przepływ": [100, 0, 100, 0.0]}, index=idx)
    assert pf.twr(d) == pytest.approx(0.21)
    # zakres od dnia 2: wartość początkowa 110, dzień2 0%, dzień3 +10%
    assert pf.twr(d, "2024-01-03") == pytest.approx(0.10)


def test_xirr_one_year_ten_percent():
    r = pf.xirr([(pd.Timestamp("2023-01-01"), -100), (pd.Timestamp("2024-01-01"), 110)])
    assert r == pytest.approx(0.10, abs=1e-3)  # 365 dni
    assert pf.xirr([(pd.Timestamp("2023-01-01"), -100)]) != pf.xirr([(pd.Timestamp("2023-01-01"), -100)])  # NaN


def test_xirr_daily_two_deposits():
    idx = pd.to_datetime(["2023-01-01", "2024-01-01", "2024-01-02"])
    d = pd.DataFrame({"wartość": [100, 100, 221.0], "przepływ": [100, 0, 100.0]}, index=idx)
    # druga wpłata 100 i wypłata 221 tego samego dnia => netto 100 -> 121 w 366 dni: r = 1.21^(365/366) - 1
    r = pf.xirr_daily(d)
    assert r == pytest.approx(1.21 ** (365 / 366) - 1, abs=1e-4)


def test_summary_dividends_commissions():
    idx = pd.date_range("2024-01-01", periods=2)
    d = pd.DataFrame({"wartość": [100.0, 105.0], "przepływ": [100.0, 0.0]}, index=idx)
    t = tr([("2024-01-01", "A.PL", "kupno", 1, 100, "PLN", 1.5, 100)])
    c = cash([("2024-01-02", "dywidenda", 10), ("2024-01-02", "podatek_u_źródła", -1.9),
              ("2024-01-02", "odsetki", 0.5), ("2024-01-02", "podatek_od_odsetek", -0.1)])
    s = pf.summary(d, t, c)
    assert s["dywidendy_netto"] == pytest.approx(8.1) and s["prowizje"] == 1.5
    assert s["odsetki_netto"] == pytest.approx(0.4) and s["zysk"] == pytest.approx(5)


def test_profit_breakdown_sums_to_overall():
    # kupno 10@10 i 10@20, sprzedaż 5@30; cena bieżąca 30: realized 75, unrealized 225, razem 300
    t = tr([("2024-01-01", "A.PL", "kupno", 10, 10, "PLN", 0, 100),
            ("2024-01-02", "A.PL", "kupno", 10, 20, "PLN", 0, 200),
            ("2024-01-03", "A.PL", "sprzedaż", 5, 30, "PLN", 0, 150),
            ("2024-01-04", "B.PL", "kupno", 1, 50, "PLN", 0, 50),
            ("2024-01-05", "B.PL", "sprzedaż", 1, 60, "PLN", 0, 60)])  # B zamknięta: +10 zrealizowane
    b = pf.profit_breakdown(t, {"A.PL": 30.0})
    assert b["niezrealizowany"] == pytest.approx(225) and b["zrealizowany"] == pytest.approx(85)
    assert b["koszt_otwartych"] == pytest.approx(225) and b["niezrealizowany_proc"] == pytest.approx(100)
    # zgodność z zyskiem gotówkowym: wartość (450) + gotówka (-100-200-50+150+60=-140) - wpłaty (0 => ujemna gotówka) 
    assert b["niezrealizowany"] + b["zrealizowany"] == pytest.approx(450 + (-140))
