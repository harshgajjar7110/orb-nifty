import pytest
import pandas as pd
from osse.data.chrome_collector import ChromeCollector
from osse.data.dom_parser import DOMParser
from osse.data.collector import DataCollector

def test_chrome_collector_config_load():
    collector = ChromeCollector()
    config = collector.get_target_config("nse_option_chain")
    
    assert config is not None
    assert config.get("name") == "NSE India Option Chain"
    assert "js_extractor" in config

def test_dom_parser_nse_option_chain():
    mock_payload = {
        "spot_price": 24500.50,
        "option_chain": [
            {
                "strike": "24400",
                "call_ltp": "180.5",
                "call_iv": "14.2",
                "call_oi": "1250000",
                "put_ltp": "75.0",
                "put_iv": "15.1",
                "put_oi": "850000"
            },
            {
                "strike": "24500",
                "call_ltp": "120.0",
                "call_iv": "13.8",
                "call_oi": "2100000",
                "put_ltp": "115.0",
                "put_iv": "14.5",
                "put_oi": "1950000"
            }
        ]
    }
    
    spot, df = DOMParser.parse_nse_option_chain(mock_payload)
    
    assert spot == 24500.50
    assert not df.empty
    assert len(df) == 2
    assert "strike" in df.columns
    assert df.iloc[0]["strike"] == 24400.0
    assert df.iloc[1]["call_ltp"] == 120.0

def test_dom_parser_generic_table():
    mock_table = {
        "headers": ["Indicator", "Value"],
        "rows": [
            ["CPR_Pivot", "24510.0"],
            ["VWAP", "24495.5"]
        ]
    }
    
    df = DOMParser.parse_generic_table(mock_table)
    
    assert not df.empty
    assert list(df.columns) == ["Indicator", "Value"]
    assert len(df) == 2
    assert df.iloc[0]["Indicator"] == "CPR_Pivot"

def test_data_collector_chrome_mcp_integration():
    mock_payload = {
        "spot_price": 24500.0,
        "option_chain": [
            {"strike": 24500, "call_ltp": 120, "call_iv": 14, "call_oi": 1000, "put_ltp": 110, "put_iv": 15, "put_oi": 1200}
        ]
    }
    
    spot, df = DataCollector.fetch_via_chrome_mcp("nse_option_chain", mock_payload)
    assert spot == 24500.0
    assert not df.empty
    assert df.iloc[0]["strike"] == 24500
