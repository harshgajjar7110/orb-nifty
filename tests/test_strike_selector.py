import pytest
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from osse.data.collector import DataCollector
from osse.options.strike_selector import StrikeSelector
from osse.engine.decision import DecisionEngine

def test_synthetic_option_chain_generation():
    chain = DataCollector.generate_synthetic_option_chain(24500.0, "NIFTY", vix=15.0, strike_depth=20)
    assert chain["symbol"] == "NIFTY"
    assert chain["spot_price"] == 24500.0
    assert chain["atm_strike"] == 24500.0
    assert len(chain["chain"]) == 41  # ±20 strikes = 41 total strikes
    assert chain["data_source"] == "synthetic_bs_engine"

def test_strike_selector_moneyness_variant():
    selector = StrikeSelector()
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="MONEYNESS",
        direction="UP"
    )
    assert res["variant_used"] == "MONEYNESS"
    assert len(res["legs"]) == 2
    assert res["legs"][0]["action"] == "SELL"
    assert res["legs"][0]["option_type"] == "PE"
    assert res["legs"][0]["strike"] == 24450.0  # ATM - 1 step
    assert res["legs"][1]["action"] == "BUY"
    assert res["legs"][1]["strike"] == 24350.0  # ATM - 3 steps

def test_strike_selector_delta_targeted_variant():
    selector = StrikeSelector()
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="DELTA_TARGETED",
        direction="UP"
    )
    assert res["variant_used"] == "DELTA_TARGETED"
    assert len(res["legs"]) == 2
    # Short leg delta should be close to 0.20
    assert abs(abs(res["legs"][0]["delta"]) - 0.20) < 0.10
    # Long leg delta should be close to 0.08
    assert abs(abs(res["legs"][1]["delta"]) - 0.08) < 0.08

def test_strike_selector_oi_wall_variant():
    selector = StrikeSelector()
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="OI_WALL",
        direction="UP"
    )
    assert res["variant_used"] == "OI_WALL"
    assert len(res["legs"]) == 2

def test_strike_selector_expected_move_variant():
    selector = StrikeSelector()
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="EXPECTED_MOVE",
        vix=16.0,
        direction="UP"
    )
    assert res["variant_used"] == "EXPECTED_MOVE"
    assert len(res["legs"]) == 2
    # Short PE strike should be below 24500
    assert res["legs"][0]["strike"] < 24500.0

def test_strike_selector_cpr_pivot_variant():
    selector = StrikeSelector()
    daily_context = {"cpr_pivot": 24500.0, "cpr_tc": 24520.0, "cpr_bc": 24480.0}
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        daily_context=daily_context,
        symbol="NIFTY",
        variant="CPR_PIVOT",
        direction="UP"
    )
    assert res["variant_used"] == "CPR_PIVOT"
    assert len(res["legs"]) == 2
    # Short PE strike should be at or below CPR BC (24480 -> rounded to 24450)
    assert res["legs"][0]["strike"] <= 24450.0

def test_expiry_manager():
    from osse.options.expiry_manager import ExpiryManager
    expiries = ExpiryManager.calculate_all_expiries("2026-07-20", "NIFTY")
    assert "WEEKLY" in expiries
    assert "NEXT_WEEKLY" in expiries
    assert "MONTHLY" in expiries
    assert expiries["WEEKLY"]["expiry_date"] == "2026-07-21"
    assert expiries["NEXT_WEEKLY"]["expiry_date"] == "2026-07-28"

def test_strike_selector_with_expiry():
    selector = StrikeSelector()
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="DELTA_TARGETED",
        expiry_type="MONTHLY",
        trade_date="2026-07-20",
        direction="UP"
    )
    assert res["expiry_type"] == "MONTHLY"
    assert "expiry_date" in res
    assert res["dte_days"] > 0
    assert len(res["legs"]) == 2

def test_strike_selector_gex_dex_aligned_variant():
    selector = StrikeSelector()
    dex_data = {
        "call_wall": 24650.0,
        "put_support": 24350.0,
        "delta_flip": 24450.0,
    }
    gex_data = {
        "gamma_flip": 24450.0,
        "peak_pos_gamma_strike": 24650.0,
        "peak_neg_gamma_strike": 24350.0,
    }
    res = selector.select_strikes(
        strategy_name="Directional Credit Spread",
        spot_price=24500.0,
        symbol="NIFTY",
        variant="GEX_DEX_ALIGNED",
        direction="UP",
        dex_data=dex_data,
        gex_data=gex_data,
    )
    assert res["variant_used"] == "GEX_DEX_ALIGNED"
    assert len(res["legs"]) == 2
    assert res["legs"][0]["action"] == "SELL"
    assert res["legs"][0]["option_type"] == "PE"
    assert res["legs"][0]["strike"] < 24500.0
    assert res["legs"][1]["strike"] < res["legs"][0]["strike"]


def test_decision_engine_with_strike_recommendation():
    decision = DecisionEngine.get_decision(
        score=78.0,
        regime="TRENDING",
        iv_rank=55.0,
        spot_price=24500.0,
        symbol="NIFTY",
        variant="DELTA_TARGETED",
        direction="UP"
    )
    assert decision["decision"] == "TRADE"
    assert "strike_recommendation" in decision
    rec = decision["strike_recommendation"]
    assert rec["symbol"] == "NIFTY"
    assert len(rec["legs"]) == 2
    assert rec["is_credit"] is True
