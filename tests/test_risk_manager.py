import pytest
from osse.engine.risk_manager import RiskManager


def test_risk_manager_position_sizing():
    rm = RiskManager(default_capital=1_000_000.0)

    # 1. Normal conditions (2% risk on ₹1,000,000 = ₹20,000 risk, max loss per lot = ₹15,000 => 1 lot)
    res = rm.calculate_position_size(capital=1_000_000.0, risk_percent=2.0, max_loss_per_lot=15_000.0)
    assert res["allowed_lots"] == 1
    assert res["risk_capital_allocated"] == 15000.0

    # 2. Level 1 Drawdown (5% DD -> 50% risk cap)
    res_dd1 = rm.calculate_position_size(capital=1_000_000.0, risk_percent=2.0, max_loss_per_lot=5_000.0, current_drawdown_pct=6.0)
    assert res_dd1["drawdown_protocol"]["level"] == "Level 1"
    assert res_dd1["drawdown_protocol"]["size_multiplier"] == 0.50

    # 3. Level 2 Drawdown (10% DD -> pause entries)
    res_dd2 = rm.calculate_position_size(capital=1_000_000.0, risk_percent=2.0, max_loss_per_lot=5_000.0, current_drawdown_pct=11.0)
    assert res_dd2["allowed_lots"] == 0
    assert res_dd2["drawdown_protocol"]["level"] == "Level 2"


def test_risk_manager_hedge_trigger():
    rm = RiskManager()
    # Spot 24630 is within 0.3% of 24650
    hedge = rm.check_dynamic_hedge_trigger(spot_price=24630.0, sold_strike=24650.0, net_position_delta=0.4)
    assert hedge["hedge_triggered"] is True

    # Spot 24000 is far from 24650
    no_hedge = rm.check_dynamic_hedge_trigger(spot_price=24000.0, sold_strike=24650.0, net_position_delta=0.4)
    assert no_hedge["hedge_triggered"] is False
