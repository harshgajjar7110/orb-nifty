import pytest
import pandas as pd
from osse.engine.dex_calculator import DEXCalculator


def test_dex_calculator_basic():
    calc = DEXCalculator(default_lot_size=75)
    
    # Mock Option Chain
    data = [
        {"strike_price": 24400, "ce_oi": 10000, "ce_delta": 0.70, "pe_oi": 150000, "pe_delta": -0.30},
        {"strike_price": 24500, "ce_oi": 50000, "ce_delta": 0.50, "pe_oi": 50000, "pe_delta": -0.50},
        {"strike_price": 24600, "ce_oi": 200000, "ce_delta": 0.30, "pe_oi": 10000, "pe_delta": -0.70},
    ]
    df = pd.DataFrame(data)

    res = calc.calculate_dex(df, lot_size=75, spot_price=24500)

    assert res["status"] == "SUCCESS"
    assert res["call_wall"] == 24600
    assert res["put_support"] == 24400
    assert res["delta_flip"] in [24400, 24500, 24600]
    assert len(res["dex_clusters"]) > 0
    assert "total_call_dex" in res
    assert "total_put_dex" in res
    assert "dex_ratio" in res
    assert res["total_call_dex"] > 0
    assert res["total_put_dex"] < 0


def test_dex_calculator_empty():
    calc = DEXCalculator()
    res = calc.calculate_dex(pd.DataFrame())
    assert res["status"] == "ERROR"
    assert res["call_wall"] == 0.0
