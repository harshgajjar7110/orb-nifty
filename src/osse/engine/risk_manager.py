"""
Risk Management Framework for OSSE.

Handles Position Sizing (Kelly / Risk Caps), Dynamic Delta Hedging triggers,
Stop Loss Rules, and 3-Level Drawdown Protocols.
"""

from typing import Dict, List, Any, Optional
import math


class RiskManager:
    """
    Risk & Position Sizing Engine for options strategy execution.
    """

    def __init__(self, default_capital: float = 1_000_000.0, max_margin_utilization: float = 0.60):
        self.default_capital = default_capital
        self.max_margin_utilization = max_margin_utilization

    def calculate_position_size(
        self,
        capital: float,
        risk_percent: float,
        max_loss_per_lot: float,
        lot_size: int = 75,
        margin_per_lot: float = 100_000.0,
        current_drawdown_pct: float = 0.0
    ) -> Dict[str, Any]:
        """
        Calculates allowed lot size based on capital risk caps and drawdown protocol reductions.
        """
        if capital <= 0 or max_loss_per_lot <= 0:
            return {
                "allowed_lots": 0,
                "risk_capital_allocated": 0.0,
                "reason": "Invalid capital or max loss per lot."
            }

        # Apply Drawdown Protocol Sizing Adjustment (PRD Section 8.4)
        dd_protocol = self.evaluate_drawdown_protocol(current_drawdown_pct)
        effective_risk_pct = risk_percent * dd_protocol["size_multiplier"]

        if not dd_protocol["allow_new_entries"]:
            return {
                "allowed_lots": 0,
                "risk_capital_allocated": 0.0,
                "drawdown_protocol": dd_protocol,
                "reason": dd_protocol["action"]
            }

        max_risk_amount = capital * (effective_risk_pct / 100.0)
        lots_by_risk = math.floor(max_risk_amount / max_loss_per_lot)

        # Margin Utilization Cap Check (60% max margin)
        available_margin_cap = capital * self.max_margin_utilization
        lots_by_margin = math.floor(available_margin_cap / margin_per_lot) if margin_per_lot > 0 else lots_by_risk

        allowed_lots = max(0, min(lots_by_risk, lots_by_margin))
        actual_risk = allowed_lots * max_loss_per_lot

        return {
            "allowed_lots": allowed_lots,
            "total_contracts": allowed_lots * lot_size,
            "risk_capital_allocated": round(actual_risk, 2),
            "effective_risk_pct": round((actual_risk / capital) * 100.0, 2) if capital > 0 else 0.0,
            "margin_required": round(allowed_lots * margin_per_lot, 2),
            "drawdown_protocol": dd_protocol
        }

    def check_dynamic_hedge_trigger(
        self,
        spot_price: float,
        sold_strike: float,
        net_position_delta: float,
        lot_size: int = 75,
        position_count: int = 1
    ) -> Dict[str, Any]:
        """
        Evaluates whether dynamic hedging is triggered (spot within 0.3% of sold strike).
        """
        if spot_price <= 0 or sold_strike <= 0:
            return {"hedge_triggered": False, "reason": "Invalid prices."}

        distance_pct = abs(spot_price - sold_strike) / spot_price
        triggered = distance_pct <= 0.003

        # Delta-neutral futures hedge ratio calculation
        futures_contracts = -round(net_position_delta * lot_size * position_count / lot_size, 2)

        return {
            "hedge_triggered": triggered,
            "distance_pct": round(distance_pct * 100.0, 3),
            "sold_strike": sold_strike,
            "spot_price": spot_price,
            "recommended_action": "Buy protective OTM option or futures hedge" if triggered else "No hedge required",
            "delta_neutral_futures_contracts": futures_contracts
        }

    def evaluate_stop_loss_triggers(
        self,
        spot_price: float,
        bought_strike: Optional[float] = None,
        dte: float = 7.0,
        entry_vix: float = 15.0,
        current_vix: float = 15.0,
        entry_dex_wall: float = 0.0,
        current_dex_wall: float = 0.0,
        step_size: float = 50.0,
        is_call_side: bool = True
    ) -> Dict[str, Any]:
        """
        Evaluates Hard Stop, Time Stop, Volatility Stop, and DEX Shift Stop rules.
        """
        stops_triggered = []

        # 1. Hard Stop: Spot closes beyond bought strike
        if bought_strike and bought_strike > 0:
            if is_call_side and spot_price >= bought_strike:
                stops_triggered.append("Hard Stop: Spot breached call buy strike")
            elif not is_call_side and spot_price <= bought_strike:
                stops_triggered.append("Hard Stop: Spot breached put buy strike")

        # 2. Time Stop: Close all at <= 2 DTE
        if dte <= 2.0:
            stops_triggered.append(f"Time Stop: Position reached {dte:.1f} DTE (assignment/gamma risk)")

        # 3. Volatility Stop: VIX spikes > 25% from entry
        if entry_vix > 0:
            vix_change_pct = (current_vix - entry_vix) / entry_vix
            if vix_change_pct >= 0.25:
                stops_triggered.append(f"Volatility Stop: India VIX spiked by {vix_change_pct*100:.1f}%")

        # 4. DEX Shift Stop: DEX wall shifts > 1 strike
        if entry_dex_wall > 0 and current_dex_wall > 0:
            shift_strikes = abs(current_dex_wall - entry_dex_wall) / step_size
            if shift_strikes > 1.0:
                stops_triggered.append(f"DEX Shift Stop: DEX wall shifted by {shift_strikes:.1f} strikes")

        return {
            "stop_triggered": len(stops_triggered) > 0,
            "triggers": stops_triggered,
            "action": "Close position immediately" if len(stops_triggered) > 0 else "Hold position"
        }

    def evaluate_drawdown_protocol(self, current_drawdown_pct: float) -> Dict[str, Any]:
        """
        Evaluates 3-Level Drawdown Protocols (PRD Section 8.4).
        """
        if current_drawdown_pct >= 15.0:
            return {
                "level": "Level 3",
                "drawdown_pct": current_drawdown_pct,
                "allow_new_entries": False,
                "size_multiplier": 0.0,
                "action": "CLOSE ALL POSITIONS. Mandatory 10-session cooling period required."
            }
        elif current_drawdown_pct >= 10.0:
            return {
                "level": "Level 2",
                "drawdown_pct": current_drawdown_pct,
                "allow_new_entries": False,
                "size_multiplier": 0.0,
                "action": "PAUSE NEW ENTRIES. Only manage existing open positions."
            }
        elif current_drawdown_pct >= 5.0:
            return {
                "level": "Level 1",
                "drawdown_pct": current_drawdown_pct,
                "allow_new_entries": True,
                "size_multiplier": 0.50,
                "action": "REDUCE POSITION SIZE BY 50% for next 5 sessions."
            }
        else:
            return {
                "level": "Normal",
                "drawdown_pct": current_drawdown_pct,
                "allow_new_entries": True,
                "size_multiplier": 1.0,
                "action": "Normal trading operations."
            }
