import sys
from unittest.mock import MagicMock

# Mock talib before any imports (mirrors tests/test_api.py)
sys.modules['talib'] = MagicMock()

import pytest
import pandas as pd
from unittest.mock import patch
from fastapi.testclient import TestClient

from osse.data.collector import DataCollector
from osse.api.app import app

client = TestClient(app)


def _sample_intraday_df() -> pd.DataFrame:
    idx = pd.date_range("2026-08-21 09:15", periods=3, freq="1min", tz="Asia/Kolkata")
    return pd.DataFrame({
        "Open": [100.0, 101.0, 102.0],
        "High": [101.0, 102.0, 103.5],
        "Low": [99.5, 100.5, 101.5],
        "Close": [100.5, 101.5, 103.0],
        "Volume": [10, 20, 30],
    }, index=idx)


def _sample_daily_df() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-08-20", "2026-08-21"]).tz_localize("Asia/Kolkata")
    return pd.DataFrame({
        "Open": [99.0, 100.0], "High": [102.0, 103.5], "Low": [98.0, 99.5],
        "Close": [100.0, 101.0], "Volume": [1000, 2000],
    }, index=idx)


class _Unresolvable:
    """Stands in for a fast_info that cannot provide previous_close."""

    def __getitem__(self, key):
        raise KeyError(key)

    def __getattr__(self, name):
        raise AttributeError(name)


JUGAAD_PAYLOAD = {
    "data": [{
        "lastPrice": 24850.35,
        "change": 123.45,
        "pChange": 0.5,
        "open": 24750.0,
        "dayHigh": 24900.0,
        "dayLow": 24700.0,
        "previousClose": 24726.90,
        "lastUpdateTime": "25-Jan-2021 16:00:00",
    }],
    "timestamp": "25-Jan-2021 16:00:00",
}


def test_fetch_spot_yfinance_canonical():
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _sample_intraday_df()
    fake_ticker.fast_info = {"previous_close": 101.0}

    with patch("yfinance.Ticker", return_value=fake_ticker):
        quote = DataCollector._fetch_spot_yfinance("^NSEI")

    assert quote["symbol"] == "^NSEI"
    assert quote["price"] == 103.0
    assert quote["open"] == 100.0
    assert quote["high"] == 103.5
    assert quote["low"] == 99.5
    assert quote["previous_close"] == 101.0
    assert quote["change"] == 2.0
    assert quote["percent_change"] == pytest.approx(1.98, abs=0.01)
    assert quote["source"] == "yfinance"
    assert quote["delayed"] is True
    assert quote["timestamp"] == "2026-08-21T09:17:00+05:30"


def test_fetch_spot_yfinance_previous_close_from_daily_history():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = _Unresolvable()
    fake_ticker.history.side_effect = [_sample_intraday_df(), _sample_daily_df()]

    with patch("yfinance.Ticker", return_value=fake_ticker):
        quote = DataCollector._fetch_spot_yfinance("^NSEI")

    assert quote["previous_close"] == 100.0
    assert quote["change"] == 3.0
    assert quote["percent_change"] == pytest.approx(3.0, abs=0.01)


def test_fetch_spot_yfinance_omits_unresolvable_previous_close():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = _Unresolvable()
    fake_ticker.history.side_effect = [_sample_intraday_df(), pd.DataFrame()]

    with patch("yfinance.Ticker", return_value=fake_ticker):
        quote = DataCollector._fetch_spot_yfinance("^NSEI")

    assert quote["price"] == 103.0
    for field in ("previous_close", "change", "percent_change"):
        assert field not in quote


def test_fetch_spot_yfinance_empty_frame_returns_empty():
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=fake_ticker):
        assert DataCollector._fetch_spot_yfinance("^NSEI") == {}


def test_fetch_spot_yfinance_raises_returns_empty():
    with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
        assert DataCollector._fetch_spot_yfinance("^NSEI") == {}


def test_fetch_spot_jugaad_canonical_and_timestamp():
    with patch("jugaad_data.nse.NSELive") as mock_nse:
        mock_nse.return_value.live_index.return_value = JUGAAD_PAYLOAD
        quote = DataCollector._fetch_spot_jugaad("^NSEI")

    mock_nse.return_value.live_index.assert_called_once_with("NIFTY 50")
    assert quote["symbol"] == "^NSEI"
    assert quote["price"] == 24850.35
    assert quote["open"] == 24750.0
    assert quote["high"] == 24900.0
    assert quote["low"] == 24700.0
    assert quote["previous_close"] == 24726.90
    assert quote["change"] == pytest.approx(123.45, abs=0.01)
    assert quote["percent_change"] == pytest.approx(0.5, abs=0.01)
    assert quote["source"] == "jugaad"
    assert quote["delayed"] is True
    # "25-Jan-2021 16:00:00" (naive IST) -> ISO-8601 Asia/Kolkata
    assert quote["timestamp"] == "2021-01-25T16:00:00+05:30"


def test_fetch_spot_jugaad_import_error_returns_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "jugaad_data", None)
    monkeypatch.setitem(sys.modules, "jugaad_data.nse", None)
    assert DataCollector._fetch_spot_jugaad("^NSEI") == {}


def test_fetch_spot_jugaad_network_failure_returns_empty():
    with patch("jugaad_data.nse.NSELive") as mock_nse:
        mock_nse.return_value.live_index.side_effect = RuntimeError("NSE 403")
        assert DataCollector._fetch_spot_jugaad("^NSEI") == {}


def test_fetch_spot_quote_falls_back_to_jugaad():
    with patch.object(DataCollector, "_fetch_spot_yfinance", return_value={}):
        with patch("jugaad_data.nse.NSELive") as mock_nse:
            mock_nse.return_value.live_index.return_value = JUGAAD_PAYLOAD
            quote = DataCollector.fetch_spot_quote("^NSEI")

    assert quote["source"] == "jugaad"
    assert quote["price"] == 24850.35


def test_fetch_spot_quote_prefers_yfinance():
    yf_quote = {"symbol": "^NSEI", "price": 103.0, "source": "yfinance", "delayed": True}
    with patch.object(DataCollector, "_fetch_spot_yfinance", return_value=yf_quote):
        with patch.object(DataCollector, "_fetch_spot_jugaad") as mock_jugaad:
            quote = DataCollector.fetch_spot_quote("NIFTY")

    assert quote["source"] == "yfinance"
    mock_jugaad.assert_not_called()


def test_fetch_spot_quote_both_fail_returns_empty():
    with patch.object(DataCollector, "_fetch_spot_yfinance", return_value={}):
        with patch.object(DataCollector, "_fetch_spot_jugaad", return_value={}):
            assert DataCollector.fetch_spot_quote("^NSEI") == {}


def test_fetch_spot_quote_unsupported_symbol_no_network():
    with patch.object(DataCollector, "_fetch_spot_yfinance") as mock_yf:
        with patch.object(DataCollector, "_fetch_spot_jugaad") as mock_jugaad:
            assert DataCollector.fetch_spot_quote("RELIANCE") == {}

    mock_yf.assert_not_called()
    mock_jugaad.assert_not_called()


def test_quote_endpoint_success():
    quote = {
        "symbol": "^NSEI", "price": 24850.35, "change": 123.45, "percent_change": 0.5,
        "open": 24750.0, "high": 24900.0, "low": 24700.0, "previous_close": 24726.90,
        "timestamp": "2021-01-25T16:00:00+05:30", "source": "jugaad", "delayed": True,
    }
    with patch("osse.api.app.DataCollector.fetch_spot_quote", return_value=quote):
        response = client.get("/api/v1/quote", params={"symbol": "^NSEI"})

    assert response.status_code == 200
    data = response.json()
    assert data["price"] == 24850.35
    assert data["change"] == 123.45
    assert data["source"] == "jugaad"
    assert data["delayed"] is True


def test_quote_endpoint_both_sources_failed():
    with patch("osse.api.app.DataCollector.fetch_spot_quote", return_value={}):
        response = client.get("/api/v1/quote", params={"symbol": "^NSEI"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Both quote sources failed"


def test_quote_endpoint_bad_symbol():
    with patch("osse.api.app.DataCollector.fetch_spot_quote") as mock_fetch:
        response = client.get("/api/v1/quote", params={"symbol": "RELIANCE"})

    assert response.status_code == 422
    mock_fetch.assert_not_called()
