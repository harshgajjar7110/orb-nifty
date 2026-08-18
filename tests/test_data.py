import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from osse.data.collector import DataCollector
from osse.data.validator import DataValidator


def test_fetch_data_yfinance_fallback():
    sample = pd.DataFrame({
        "Open": [100.0], "High": [105.0], "Low": [95.0], "Close": [102.0], "Volume": [1000]
    })
    sample.index = pd.to_datetime(["2026-07-14 09:15:00"]).tz_localize("Asia/Kolkata")

    with patch.object(DataCollector, "_fetch_data_yfinance", return_value=sample):
        df = DataCollector.fetch_data("NIFTY", "2026-07-14")

    assert not df.empty
    assert "Open" in df.columns
    assert "Volume" in df.columns
    assert df["Close"].iloc[0] == 102.0


def test_fetch_data_empty():
    with patch.object(DataCollector, "_fetch_data_yfinance", return_value=pd.DataFrame()):
        df = DataCollector.fetch_data("NIFTY", "2026-07-14")
    assert df.empty


def test_fetch_daily_context_yfinance():
    context = {
        "prev_close": 104.0,
        "prev_high": 106.0,
        "prev_low": 96.0,
        "daily_volume": 2000.0,
        "cpr_pivot": 102.0,
        "cpr_tc": 103.0,
        "cpr_bc": 101.0,
        "cpr_width": 1.0,
        "daily_trend": 1.0,
        "daily_ema20": 103.0,
        "vix": 15.0,
        "iv_rank": 50.0,
        "iv_percentile": 50.0,
    }
    with patch.object(DataCollector, "_fetch_daily_context_yfinance", return_value=context):
        result = DataCollector.fetch_daily_context("NIFTY", "2026-07-14")

    assert result["prev_close"] == 104.0
    assert result["daily_volume"] == 2000.0


def test_fetch_daily_context_jugaad_fallback():
    context = {"prev_close": 250.0, "vix": 14.0}

    with patch.object(DataCollector, "_fetch_daily_context_yfinance", return_value={}):
        with patch.object(DataCollector, "_fetch_daily_context_jugaad", return_value=context):
            result = DataCollector.fetch_daily_context("NIFTY", "2026-07-14")

    assert result["prev_close"] == 250.0


def test_extract_context_metrics():
    dates = pd.date_range("2026-07-13", "2026-07-14", freq="1D")
    daily = pd.DataFrame({
        "Open": [100.0, 102.0], "High": [105.0, 106.0], "Low": [95.0, 96.0],
        "Close": [102.0, 104.0], "Volume": [1000, 2000]
    }, index=dates)
    daily.index.name = "Date"

    context = DataCollector._extract_context_metrics(daily, "2026-07-14")

    assert context["prev_close"] == 104.0
    assert context["daily_volume"] == 2000.0
    assert "cpr_pivot" in context
    assert "vix" in context


def test_normalise_frame_lowercase():
    raw = pd.DataFrame({
        "date": ["2026-07-14 09:15:00"],
        "open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000],
    })
    df = DataCollector._normalise_frame(raw)

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)


def test_validate_intraday_data_empty():
    assert not DataValidator.validate_intraday_data(pd.DataFrame())
    assert not DataValidator.validate_intraday_data(None)


def test_validate_intraday_data_missing_columns():
    df = pd.DataFrame({"Open": [100]})
    assert not DataValidator.validate_intraday_data(df)


def test_validate_intraday_data_valid():
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:30", freq="1min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        "Open": [100] * 16, "High": [105] * 16, "Low": [95] * 16, "Close": [102] * 16, "Volume": [1000] * 16
    }, index=dates)
    assert DataValidator.validate_intraday_data(df)


def test_validate_daily_context():
    assert not DataValidator.validate_daily_context({})
    assert not DataValidator.validate_daily_context({"prev_close": 100})

    valid_context = {"prev_close": 100, "prev_high": 105, "prev_low": 95, "daily_volume": 1000}
    assert DataValidator.validate_daily_context(valid_context)
