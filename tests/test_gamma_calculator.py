import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import pandas as pd
import pytest

from osse.engine.gamma_calculator import GammaExposureCalculator


def test_gamma_calculator_basic():
    calc = GammaExposureCalculator(default_lot_size=75)
    data = [
        {"strike_price": 24400, "ce_oi": 10000, "ce_gamma": 0.001, "pe_oi": 150000, "pe_gamma": 0.001},
        {"strike_price": 24500, "ce_oi": 50000, "ce_gamma": 0.0012, "pe_oi": 50000, "pe_gamma": 0.0012},
        {"strike_price": 24600, "ce_oi": 200000, "ce_gamma": 0.0008, "pe_oi": 10000, "pe_gamma": 0.0008},
    ]
    df = pd.DataFrame(data)
    res = calc.calculate_gex(df, lot_size=75, spot_price=24500)

    assert res["status"] == "SUCCESS"
    assert res["peak_pos_gamma_strike"] in [24500.0, 24600.0]
    assert res["total_call_gex"] > 0
    assert res["total_put_gex"] > 0
    assert res["gamma_flip"] in [24400.0, 24500.0, 24600.0]


def test_gamma_calculator_empty():
    calc = GammaExposureCalculator()
    res = calc.calculate_gex(pd.DataFrame())
    assert res["status"] == "ERROR"
    assert res["peak_pos_gamma_strike"] == 0.0


def test_gamma_calculator_missing_gamma_columns():
    calc = GammaExposureCalculator(default_lot_size=75)
    data = [
        {"strike_price": 24400, "ce_oi": 10000, "pe_oi": 150000},
        {"strike_price": 24500, "ce_oi": 50000, "pe_oi": 50000},
        {"strike_price": 24600, "ce_oi": 200000, "pe_oi": 10000},
    ]
    df = pd.DataFrame(data)
    res = calc.calculate_gex(df, lot_size=75, spot_price=24500)
    assert res["status"] == "SUCCESS"
    assert res["peak_pos_gamma_strike"] > 0
