import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from osse.data.collector import DataCollector
from osse.data.validator import DataValidator

@pytest.fixture
def mock_dhan():
    DataCollector._client = None
    with patch('osse.data.collector.dhanhq') as mock:
        instance = MagicMock()
        mock.return_value = instance
        # Also mock env vars
        with patch.dict('os.environ', {'dhan_client_id': 'test', 'dhan_access_token': 'test'}):
            yield instance
    DataCollector._client = None

def test_fetch_data_success(mock_dhan):
    # Mock dhan API response
    mock_dhan.intraday_minute_data.return_value = {
        "status": "success",
        "data": {
            "start_Time": ["2026-07-14 09:15:00"],
            "open": [100.0],
            "high": [105.0],
            "low": [95.0],
            "close": [102.0],
            "volume": [1000]
        }
    }
    
    df = DataCollector.fetch_data("NIFTY", "2026-07-14")
    
    assert not df.empty
    assert 'Open' in df.columns
    assert 'Volume' in df.columns
    assert df['Close'].iloc[0] == 102.0

def test_fetch_data_empty(mock_dhan):
    mock_dhan.intraday_minute_data.return_value = {"status": "failure"}
    
    df = DataCollector.fetch_data("NIFTY", "2026-07-14")
    assert df.empty

def test_fetch_daily_context(mock_dhan):
    mock_dhan.historical_daily_data.return_value = {
        "status": "success",
        "data": {
            "start_Time": ["2026-07-13", "2026-07-14"],
            "open": [100, 102],
            "high": [105, 106],
            "low": [95, 96],
            "close": [102, 104],
            "volume": [1000, 2000]
        }
    }
    
    context = DataCollector.fetch_daily_context("NIFTY", "2026-07-14")
    
    assert context['prev_close'] == 104.0
    assert context['daily_volume'] == 2000.0

def test_validate_intraday_data_empty():
    assert not DataValidator.validate_intraday_data(pd.DataFrame())
    assert not DataValidator.validate_intraday_data(None)

def test_validate_intraday_data_missing_columns():
    df = pd.DataFrame({'Open': [100]})
    assert not DataValidator.validate_intraday_data(df)

def test_validate_intraday_data_valid():
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:30", freq="1min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        'Open': [100]*16, 'High': [105]*16, 'Low': [95]*16, 'Close': [102]*16, 'Volume': [1000]*16
    }, index=dates)
    assert DataValidator.validate_intraday_data(df)

def test_validate_daily_context():
    assert not DataValidator.validate_daily_context({})
    assert not DataValidator.validate_daily_context({'prev_close': 100})
    
    valid_context = {'prev_close': 100, 'prev_high': 105, 'prev_low': 95, 'daily_volume': 1000}
    assert DataValidator.validate_daily_context(valid_context)

