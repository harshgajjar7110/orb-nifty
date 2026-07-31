import pytest
from osse.data.dhan_mcp import DhanMCPCollector


def test_dhan_mcp_collector_fallback():
    collector = DhanMCPCollector(data_dir="non_existent_dir_for_fallback")

    # Fetch option chain should return valid synthetic fallback dataframe
    chain_df = collector.fetch_option_chain(symbol="NIFTY")
    assert chain_df is not None
    assert not chain_df.empty
    assert "strike_price" in chain_df.columns
    assert "ce_oi" in chain_df.columns

    # Fetch candles should return valid synthetic fallback dataframe
    candles_df = collector.fetch_chart_candles(symbol="NIFTY")
    assert candles_df is not None
    assert not candles_df.empty
    assert "close" in candles_df.columns
    assert "volume" in candles_df.columns
