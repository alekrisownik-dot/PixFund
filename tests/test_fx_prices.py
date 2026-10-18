import pandas as pd
import pytest
import requests

from core import fx, prices


def fake_nbp(calls):
    def fetch(code, a, b):
        calls.append((code, a, b))
        days = [d for d in pd.date_range(a, b) if d.weekday() < 5]
        return pd.Series({d: 4.0 + d.day / 100 for d in days})
    return fetch


def test_fx_weekend_and_previous_day(tmp_path):
    db, calls = tmp_path / "c.db", []
    r = fx.get_rates("EUR", "2024-03-01", "2024-03-20", db, fetcher=fake_nbp(calls))
    # 2024-03-09 to sobota: kurs z piątku 08.03 (4.08); 'poprzedni dzień' dla poniedziałku 11.03 też piątek
    assert fx.rate_on(r, "2024-03-09") == pytest.approx(4.08)
    assert fx.rate_on(r, "2024-03-11", previous_day=True) == pytest.approx(4.08)
    assert fx.rate_on(r, "2024-03-12", previous_day=True) == pytest.approx(4.11)
    with pytest.raises(KeyError):
        fx.rate_on(r, "2000-01-01")


def test_fx_cache_fetches_only_missing(tmp_path):
    db, calls = tmp_path / "c.db", []
    f = fake_nbp(calls)
    fx.get_rates("USD", "2024-03-01", "2024-03-20", db, fetcher=f)
    n = len(calls)
    fx.get_rates("USD", "2024-03-05", "2024-03-15", db, fetcher=f)
    assert len(calls) == n  # w całości z cache
    fx.get_rates("USD", "2024-03-01", "2024-04-10", db, fetcher=f)
    assert len(calls) == n + 1 and calls[-1][1] == pd.Timestamp("2024-03-21").date()


def test_fx_pln_and_daily():
    assert (fx.get_rates("PLN", "2024-01-01", "2024-01-03") == 1).all()
    s = pd.Series([4.0, 4.5], index=pd.to_datetime(["2024-03-08", "2024-03-11"]))
    d = fx.daily_rates(s, "2024-03-08", "2024-03-11")
    assert list(d) == [4.0, 4.0, 4.0, 4.5]


@pytest.mark.parametrize("t,src,expected", [
    ("PKN.PL", "stooq", "pkn"), ("PKN.PL", "yahoo", "PKN.WA"),
    ("AAPL.US", "stooq", "aapl.us"), ("AAPL.US", "yahoo", "AAPL"),
    ("EUNL.DE", "stooq", "eunl.de"), ("EUNL.DE", "yahoo", "EUNL.DE"),
    ("VUSA.UK", "yahoo", "VUSA.L"), ("WIG20", "yahoo", "ETFBW20TR.WA"), ("^SPX", "stooq", "^spx"), ("^NDX", "yahoo", "^NDX"),
])
def test_symbol_mapping(t, src, expected):
    assert prices.to_source_symbol(t, src) == expected


def _ohlcv(a, b):
    idx = pd.bdate_range(a, b)
    return pd.DataFrame({c: range(1, len(idx) + 1) for c in prices.OHLCV}, index=idx, dtype=float)


def test_prices_fallback_and_cache(tmp_path):
    db, calls = tmp_path / "p.db", []

    def stooq_down(t, a, b):
        calls.append("stooq")
        raise requests.ConnectionError()

    def yahoo(t, a, b):
        calls.append("yahoo")
        return _ohlcv(a, b)

    f = [("stooq", stooq_down), ("yahoo", yahoo)]
    df = prices.get_prices("PKN.PL", "2024-03-04", "2024-03-08", db, f)
    assert calls == ["stooq", "yahoo"] and len(df) == 5 and df["close"].iloc[-1] == 5
    prices.get_prices("PKN.PL", "2024-03-05", "2024-03-07", db, f)
    assert calls == ["stooq", "yahoo"]  # z cache


def test_prices_empty_stooq_falls_back(tmp_path):
    f = [("stooq", lambda t, a, b: prices._empty()), ("yahoo", lambda t, a, b: _ohlcv(a, b))]
    assert len(prices.get_prices("X.US", "2024-03-04", "2024-03-08", tmp_path / "p.db", f)) == 5


def test_stooq_challenge_page_raises(monkeypatch):
    class R:
        text = "<!DOCTYPE html><html>...JavaScript...</html>"
        def raise_for_status(self): pass
    monkeypatch.setattr(prices.requests, "get", lambda *a, **k: R())
    with pytest.raises(prices.SourceUnavailable):
        prices.fetch_stooq("PKN.PL", "2024-01-01", "2024-01-31")


def test_failed_source_is_skipped_for_cooldown(tmp_path):
    prices._down_since.clear()
    calls = []

    def down(t, a, b):
        calls.append(t)
        raise requests.ConnectTimeout()

    f = [("stooq", down), ("yahoo", lambda t, a, b: _ohlcv(a, b))]
    prices.get_prices("A.US", "2024-03-04", "2024-03-08", tmp_path / "p.db", f)
    prices.get_prices("B.US", "2024-03-04", "2024-03-08", tmp_path / "p.db", f)
    assert calls == ["A.US"]  # drugi ticker nie czeka na martwe źródło
    prices._down_since.clear()
