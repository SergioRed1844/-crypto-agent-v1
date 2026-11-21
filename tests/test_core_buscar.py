import core.buscar_cripto as bc


def test_ficha_sin_red(monkeypatch):
    monkeypatch.setattr(bc, "get", lambda url, tries=5: {"name": "X", "symbol": "x", "market_data": {"current_price": {"usd": 2.0}, "ath": {"usd": 3.0}}, "tickers": []})
    import pandas as pd
    monkeypatch.setattr(bc, "serie", lambda cid: pd.Series(dtype=float))
    f = bc.ficha("x")
    assert f["precio"] == 2.0 and f["ath"] == 3.0 and f["mercados"] == []
