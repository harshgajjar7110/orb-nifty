import sys
from unittest.mock import MagicMock
sys.modules['talib'] = MagicMock()

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering

@patch('osse.features.indicators.talib')
def test_add_indicators(mock_talib):
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:30", freq="1min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        'Open': [100]*16, 'High': [105]*16, 'Low': [95]*16, 'Close': [102]*16, 'Volume': [1000]*16
    }, index=dates)

    mock_talib.EMA.return_value = pd.Series([100]*16, index=dates)
    mock_talib.ATR.return_value = pd.Series([10]*16, index=dates)
    mock_talib.RSI.return_value = pd.Series([50]*16, index=dates)
    mock_talib.ADX.return_value = pd.Series([20]*16, index=dates)
    mock_talib.BBANDS.return_value = (pd.Series([110]*16, index=dates), pd.Series([100]*16, index=dates), pd.Series([90]*16, index=dates))

    result = IndicatorEngine.add_indicators(df)
    
    assert not result.empty
    assert 'EMA_20' in result.columns
    assert 'VWAP' in result.columns

def test_calculate_orb_stats():
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:29", freq="1min", tz="Asia/Kolkata")
    df = pd.DataFrame({
        'Open': [100]*15, 'High': [105]*15, 'Low': [95]*15, 'Close': [102]*15, 'Volume': [1000]*15
    }, index=dates)
    
    stats = ORBBuilder.calculate_orb_stats(df, prev_close=100)
    
    assert stats['orb_high'] == 105
    assert stats['orb_low'] == 95
    assert stats['orb_width'] == 10
    assert stats['orb_percent'] == 10.0
    assert stats['orb_volume'] == 15000

def test_extract_features():
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:29", freq="1min", tz="Asia/Kolkata")
    intraday_df = pd.DataFrame({
        'Open': [100]*15, 'High': [105]*15, 'Low': [95]*15, 'Close': [102]*15, 'Volume': [1000]*15,
        'VWAP': [101]*15, 'EMA_20': [100]*15, 'EMA_50': [99]*15, 'ATR_14': [10]*15, 'ADX_14': [25]*15, 'RSI_14': [60]*15
    }, index=dates)
    
    orb_stats = {
        'orb_percent': 10.0,
        'orb_volume': 15000,
        'orb_width': 10,
        'candle_efficiency': 0.8
    }
    daily_context = {
        'daily_volume': 375000,
        'prev_close': 100
    }
    
    features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context)
    
    assert features['orb_width'] == 10.0
    assert features['adx'] == 25
    assert features['ema_alignment'] == 1.0
    assert features['atr_expansion'] == 1.0

def test_extract_features_nan_guards():
    """Ensure NaN values in indicators are sanitized to valid floats."""
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:29", freq="1min", tz="Asia/Kolkata")
    intraday_df = pd.DataFrame({
        'Open': [100]*15, 'High': [105]*15, 'Low': [95]*15, 'Close': [102]*15, 'Volume': [1000]*15,
        'VWAP': [np.nan]*15, 'EMA_20': [np.nan]*15, 'EMA_50': [np.nan]*15, 'ATR_14': [np.nan]*15,
        'ADX_14': [np.nan]*15, 'RSI_14': [np.nan]*15
    }, index=dates)
    
    orb_stats = {
        'orb_percent': 10.0,
        'orb_volume': 0,
        'orb_width': 10,
        'candle_efficiency': 0.8
    }
    daily_context = {
        'daily_volume': 0,
        'prev_close': 100
    }
    
    features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context)
    
    for key, val in features.items():
        assert isinstance(val, (int, float)), f"Feature {key} is not a number: {type(val)}"
        assert not (isinstance(val, float) and np.isnan(val)), f"Feature {key} is NaN"

def test_extract_features_zero_volume_index():
    """Ensure relative_volume produces valid values for index symbols with zero volume."""
    dates = pd.date_range("2023-01-01 09:15", "2023-01-01 09:29", freq="1min", tz="Asia/Kolkata")
    intraday_df = pd.DataFrame({
        'Open': [100]*15, 'High': [105]*15, 'Low': [95]*15, 'Close': [102]*15, 'Volume': [0]*15,
        'VWAP': [101]*15, 'EMA_20': [100]*15, 'EMA_50': [99]*15, 'ATR_14': [0]*15,
        'ADX_14': [25]*15, 'RSI_14': [60]*15
    }, index=dates)
    
    orb_stats = {
        'orb_percent': 10.0,
        'orb_volume': 0,
        'orb_width': 10,
        'candle_efficiency': 0.8
    }
    daily_context = {
        'daily_volume': 0,
        'prev_close': 100
    }
    
    features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context)
    
    assert features['relative_volume'] >= 1.0
    assert features['relative_volume'] <= 2.5
    assert not (isinstance(features['relative_volume'], float) and np.isnan(features['relative_volume']))

