import numpy as np
import pandas as pd
import pytest

from core import indicators as ind


def S(*v):
    return pd.Series(v, dtype=float)


def test_sma_ema_wma():
    s = S(1, 2, 3, 4, 5)
    assert ind.sma(s, 3).tolist()[2:] == [2, 3, 4] and ind.sma(s, 3).iloc[:2].isna().all()
    # span=3 -> alpha=0.5, start od pierwszej wartości
    assert ind.ema(s, 3).tolist()[2:] == pytest.approx([2.25, 3.125, 4.0625])
    assert ind.wma(S(1, 2, 3), 3).iloc[-1] == pytest.approx(14 / 6)


def test_bollinger():
    b = ind.bollinger(S(1, 2, 3), n=3, k=2)
    sd = np.std([1, 2, 3])
    assert b["mid"].iloc[-1] == 2 and b["upper"].iloc[-1] == pytest.approx(2 + 2 * sd)
    assert b["lower"].iloc[-1] == pytest.approx(2 - 2 * sd)


def test_rsi_wilder():
    r = ind.rsi(S(1, 2, 3, 2), n=2)
    assert r.iloc[:2].isna().all() and r.iloc[2] == 100 and r.iloc[3] == pytest.approx(50)
    assert ind.rsi(S(5, 4, 3, 2, 1), 2).iloc[-1] == 0


def test_macd():
    m = ind.macd(S(1, 2, 3, 4), fast=2, slow=3, signal=2)
    assert m["macd"].iloc[-1] == pytest.approx(3.518519 - 3.125, abs=1e-5)
    assert m["hist"].iloc[-1] == pytest.approx(m["macd"].iloc[-1] - m["signal"].iloc[-1])


def test_stochastic():
    st = ind.stochastic(S(3, 4, 5), S(1, 2, 3), S(2, 3, 5), k=3, d=1)
    assert st["k"].iloc[-1] == 100
    st = ind.stochastic(S(3, 4, 5), S(1, 2, 3), S(2, 3, 3), k=3, d=1)
    assert st["k"].iloc[-1] == pytest.approx(50)


def test_atr():
    a = ind.atr(S(10, 12, 11), S(8, 9, 9), S(9, 11, 10), n=2)
    assert a.iloc[1] == 2.5 and a.iloc[2] == pytest.approx(2.25) and np.isnan(a.iloc[0])


def test_obv():
    assert ind.obv(S(10, 11, 10, 10), S(5, 3, 2, 4)).tolist() == [0, 3, 1, 1]


def test_pivots():
    sup, res = ind.pivots(S(1, 3, 1, 2, 5, 2, 1), S(3, 1, 3, 2, 3, 0, 3), window=1)
    assert res.to_dict() == {1: 3, 4: 5}
    assert sup.to_dict() == {1: 1, 3: 2, 5: 0}


def test_cross_signals():
    sig = ind.cross_signals(S(1, 2, 3, 2, 1), S(2, 2, 2, 2, 2))
    assert sig.tolist() == [0, 0, 1, 0, -1]
    assert ind.cross_signals(S(3, 3, 3), S(2, 2, 2)).tolist() == [0, 0, 0]  # brak przecięcia bez zmiany stanu
