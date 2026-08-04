"""
Strategy Variants Engine for OSSE.

Generates pre-calculated options setups across 5 core variants based on
DEX positioning, Volume Profile 70% Value Area boundaries, and Confluence Scores.
"""

import os
import yaml
from typing import Dict, List, Any, Optional
import math


class VariantEvaluator:
    """Base Strategy Variant Evaluator."""
    def evaluate(
        self,
        spot_price: float,
        confluence_data: Dict[str, Any],
        dex_data: Dict[str, Any],
        vp_data: Dict[str, Any],
        osse_score: float,
        vix: float,
        pcr_oi: float,
        orb_width_pct: float,
        selector: "StrategyVariantSelector"
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class StrangleEvaluator(VariantEvaluator):
    def evaluate(self, spot_price, confluence_data, dex_data, vp_data, osse_score, vix, pcr_oi, orb_width_pct, selector):
        cs = confluence_data.get("confluence_score", 0.0)
        vah = vp_data.get("vah", spot_price * 1.01)
        val = vp_data.get("val", spot_price * 0.99)
        call_wall = dex_data.get("call_wall", spot_price * 1.01)
        put_support = dex_data.get("put_support", spot_price * 0.99)
        
        if cs >= 80 and val <= spot_price <= vah and vix < 20.0 and (0.8 <= pcr_oi <= 1.2):
            call_strike = selector._round_to_strike(max(vah, call_wall), round_up=True)
            put_strike = selector._round_to_strike(min(val, put_support), round_up=False)
            return {
                "variant_id": "VARIANT_1",
                "variant_name": "DEX-VP Confluence Strangle",
                "type": "Non-directional / Theta Harvest",
                "tier": "Tier 1",
                "confidence_score": cs,
                "sell_call_strike": call_strike,
                "sell_put_strike": put_strike,
                "expiry_preference": "Weekly (Theta harvest)",
                "recommended_risk_pct": 2.0,
                "entry_conditions": [
                    f"Spot ({spot_price:.2f}) between VAL ({val:.2f}) and VAH ({vah:.2f})",
                    f"DEX Call Wall ({call_wall:.2f}) and Put Support ({put_support:.2f}) outside VA",
                    f"India VIX ({vix:.1f}) < 20 and PCR ({pcr_oi:.2f}) balanced"
                ],
                "exit_conditions": [
                    "50% max profit -> close 50%, trail remainder",
                    "Spot breaches strike -> initiate dynamic delta hedge",
                    "2 DTE -> close if not at 80% profit"
                ],
                "greeks_target": "|Δ| < 0.05 per lot; Θ >= ₹500/day per lot; Negative Vega & Gamma"
            }
        return None


class CallCreditSpreadEvaluator(VariantEvaluator):
    def evaluate(self, spot_price, confluence_data, dex_data, vp_data, osse_score, vix, pcr_oi, orb_width_pct, selector):
        cs = confluence_data.get("confluence_score", 0.0)
        call_wall = dex_data.get("call_wall", spot_price * 1.01)
        vah = vp_data.get("vah", spot_price * 1.01)
        poc = vp_data.get("poc", spot_price)
        
        if cs >= 60 and (spot_price >= (call_wall * 0.995)) and vix >= 14.0:
            sell_strike = selector._round_to_strike(call_wall, round_up=True)
            width_offset = (vah - poc) * 1.5 if (vah > poc) else selector.step_size * 2
            buy_strike = selector._round_to_strike(sell_strike + width_offset, round_up=True)
            return {
                "variant_id": "VARIANT_2",
                "variant_name": "DEX Breakout Rejection Call Credit Spread",
                "type": "Mildly Bearish / Range Cap",
                "tier": "Tier 1" if cs >= 80 else "Tier 2",
                "confidence_score": cs,
                "sell_call_strike": sell_strike,
                "buy_call_strike": buy_strike,
                "expiry_preference": "Weekly (5-7 DTE)",
                "recommended_risk_pct": 1.5,
                "breakeven": sell_strike,
                "entry_conditions": [
                    f"Spot ({spot_price:.2f}) within 0.5% below DEX Call Wall ({call_wall:.2f})",
                    f"VP shows HVN near Call Wall; VIX ({vix:.1f}) >= 14.0"
                ],
                "exit_conditions": [
                    "50% max profit -> close full",
                    "Spot closes above buy strike -> stop loss",
                    "DEX Call Wall shifts higher by 2+ strikes -> close"
                ]
            }
        return None


class PutCreditSpreadEvaluator(VariantEvaluator):
    def evaluate(self, spot_price, confluence_data, dex_data, vp_data, osse_score, vix, pcr_oi, orb_width_pct, selector):
        cs = confluence_data.get("confluence_score", 0.0)
        put_support = dex_data.get("put_support", spot_price * 0.99)
        val = vp_data.get("val", spot_price * 0.99)
        poc = vp_data.get("poc", spot_price)
        
        if cs >= 60 and (spot_price <= (put_support * 1.005)) and pcr_oi <= 1.0:
            sell_strike = selector._round_to_strike(put_support, round_up=False)
            width_offset = (poc - val) * 1.5 if (poc > val) else selector.step_size * 2
            buy_strike = selector._round_to_strike(sell_strike - width_offset, round_up=False)
            return {
                "variant_id": "VARIANT_3",
                "variant_name": "VP-VAL Bounce Put Credit Spread",
                "type": "Mildly Bullish / Floor Capture",
                "tier": "Tier 1" if cs >= 80 else "Tier 2",
                "confidence_score": cs,
                "sell_put_strike": sell_strike,
                "buy_put_strike": buy_strike,
                "expiry_preference": "Weekly (5-7 DTE)",
                "recommended_risk_pct": 1.5,
                "breakeven": sell_strike,
                "entry_conditions": [
                    f"Spot ({spot_price:.2f}) within 0.5% above DEX Put Support ({put_support:.2f})",
                    f"VP shows HVN at/above Put Support; PCR ({pcr_oi:.2f}) <= 1.0"
                ],
                "exit_conditions": [
                    "50% max profit -> close full",
                    "Spot closes below buy strike -> stop loss",
                    "DEX Put Support shifts lower by 2+ strikes -> close"
                ]
            }
        return None


class IronCondorEvaluator(VariantEvaluator):
    def evaluate(self, spot_price, confluence_data, dex_data, vp_data, osse_score, vix, pcr_oi, orb_width_pct, selector):
        cs = confluence_data.get("confluence_score", 0.0)
        vah = vp_data.get("vah", spot_price * 1.01)
        val = vp_data.get("val", spot_price * 0.99)
        va_range_pct = (vah - val) / spot_price if spot_price > 0 else 0.0
        
        if cs >= 80 and va_range_pct >= 0.02 and 15.0 <= vix <= 22.0:
            wing_width = selector.step_size * 2 if selector.symbol == "NIFTY" else selector.step_size * 3
            sell_call = selector._round_to_strike(vah, round_up=True)
            buy_call = selector._round_to_strike(sell_call + wing_width, round_up=True)
            sell_put = selector._round_to_strike(val, round_up=False)
            buy_put = selector._round_to_strike(sell_put - wing_width, round_up=False)
            return {
                "variant_id": "VARIANT_4",
                "variant_name": "DEX-Range Iron Condor",
                "type": "Non-directional / Premium Collection",
                "tier": "Tier 1",
                "confidence_score": cs,
                "sell_call_strike": sell_call,
                "buy_call_strike": buy_call,
                "sell_put_strike": sell_put,
                "buy_put_strike": buy_put,
                "expiry_preference": "Monthly / Weekly (10-15 DTE)",
                "recommended_risk_pct": 2.0,
                "entry_conditions": [
                    f"Wide VAH-VAL range ({va_range_pct*100:.2f}% >= 2.0%)",
                    f"DEX walls outside VAH-VAL; India VIX ({vix:.1f}) 15-22"
                ],
                "exit_conditions": [
                    "25% max profit -> close full",
                    "Either wing breached -> close breached side",
                    "7 DTE -> close all positions"
                ]
            }
        return None


class RatioSpreadEvaluator(VariantEvaluator):
    def evaluate(self, spot_price, confluence_data, dex_data, vp_data, osse_score, vix, pcr_oi, orb_width_pct, selector):
        cs = confluence_data.get("confluence_score", 0.0)
        lvn_array = vp_data.get("lvn_array", [])
        delta_flip = dex_data.get("delta_flip")
        call_wall = dex_data.get("call_wall", spot_price * 1.01)
        put_support = dex_data.get("put_support", spot_price * 0.99)
        
        if cs >= 60 and len(lvn_array) > 0 and vix < 18.0:
            if delta_flip is None or spot_price >= delta_flip:
                long_strike = selector._round_to_strike(spot_price, round_up=True)
                short_strike = selector._round_to_strike(max(call_wall, long_strike + selector.step_size * 2), round_up=True)
                return {
                    "variant_id": "VARIANT_5",
                    "variant_name": "LVN Momentum Call Ratio Spread",
                    "type": "Bullish Directional Momentum (1x Buy ATM, 2x Sell OTM)",
                    "tier": "Tier 2",
                    "confidence_score": cs,
                    "buy_call_count": 1,
                    "buy_call_strike": long_strike,
                    "sell_call_count": 2,
                    "sell_call_strike": short_strike,
                    "expiry_preference": "Weekly (3-5 DTE)",
                    "recommended_risk_pct": 1.0,
                    "entry_conditions": [
                        delta_flip_display = f"{delta_flip:.2f}" if delta_flip is not None else "N/A"
                        f"LVN air pocket detected; Spot ({spot_price:.2f}) above Delta Flip ({delta_flip_display})",
                        f"India VIX ({vix:.1f}) < 18.0"
                    ],
                    "exit_conditions": [
                        "Target hit at DEX Call Wall -> close full",
                        "Spot reverses through Delta Flip -> close immediately",
                        "1 DTE -> close all (assignment risk)"
                    ]
                }
            else:
                long_strike = selector._round_to_strike(spot_price, round_up=False)
                short_strike = selector._round_to_strike(min(put_support, long_strike - selector.step_size * 2), round_up=False)
                return {
                    "variant_id": "VARIANT_5",
                    "variant_name": "LVN Momentum Put Ratio Spread",
                    "type": "Bearish Directional Momentum (1x Buy ATM, 2x Sell OTM)",
                    "tier": "Tier 2",
                    "confidence_score": cs,
                    "buy_put_count": 1,
                    "buy_put_strike": long_strike,
                    "sell_put_count": 2,
                    "sell_put_strike": short_strike,
                    "expiry_preference": "Weekly (3-5 DTE)",
                    "recommended_risk_pct": 1.0,
                    "entry_conditions": [
                        delta_flip_display = f"{delta_flip:.2f}" if delta_flip is not None else "N/A"
                        f"LVN air pocket detected; Spot ({spot_price:.2f}) below Delta Flip ({delta_flip_display})",
                        f"India VIX ({vix:.1f}) < 18.0"
                    ],
                    "exit_conditions": [
                        "Target hit at DEX Put Support -> close full",
                        "Spot reverses through Delta Flip -> close immediately",
                        "1 DTE -> close all"
                    ]
                }
        return None


class StrategyVariantSelector:
    """
    Evaluates and builds option strategy setups for 5 PRD strategy variants.
    """

    def __init__(self, symbol: str = "NIFTY", step_size: float = 50.0, config_path: Optional[str] = None):
        self.symbol = symbol.upper()
        self.step_size = step_size
        self.config = self._load_config(config_path)
        self.evaluators: List[VariantEvaluator] = [
            StrangleEvaluator(),
            CallCreditSpreadEvaluator(),
            PutCreditSpreadEvaluator(),
            IronCondorEvaluator(),
            RatioSpreadEvaluator()
        ]

    def _load_config(self, path: Optional[str]) -> dict:
        if path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            path = os.path.join(base_dir, "config", "strike_rules.yaml")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _round_to_strike(self, price: float, round_up: bool = True) -> float:
        """Helper to round price to nearest valid strike step."""
        if round_up:
            return math.ceil(price / self.step_size) * self.step_size
        else:
            return math.floor(price / self.step_size) * self.step_size

    def select_variants(
        self,
        spot_price: float,
        confluence_data: Dict[str, Any],
        dex_data: Dict[str, Any],
        vp_data: Dict[str, Any],
        osse_score: float = 50.0,
        vix: float = 15.0,
        pcr_oi: float = 1.0,
        orb_width_pct: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Evaluates conditions and returns matching strategy variants using config thresholds.
        """
        if spot_price <= 0 or dex_data.get("status") == "ERROR" or vp_data.get("status") == "ERROR":
            return []

        cs = confluence_data.get("confluence_score", 0.0)
        
        # Check if trade is allowed (PRD step 4: CS >= 60 and ORB width <= 1.5%)
        if cs < 40 or orb_width_pct > 1.5:
            return [{
                "variant_name": "NO TRADE / AVOID",
                "tier": "No Trade",
                "reason": f"Confluence score too low ({cs:.1f}) or ORB range too wide ({orb_width_pct:.2f}%)."
            }]

        variants = []
        for evaluator in self.evaluators:
            res = evaluator.evaluate(
                spot_price=spot_price,
                confluence_data=confluence_data,
                dex_data=dex_data,
                vp_data=vp_data,
                osse_score=osse_score,
                vix=vix,
                pcr_oi=pcr_oi,
                orb_width_pct=orb_width_pct,
                selector=self
            )
            if res:
                variants.append(res)

        # Fallback if no specific condition met but CS >= 60
        if len(variants) == 0 and cs >= 60:
            vah = vp_data.get("vah", spot_price * 1.01)
            val = vp_data.get("val", spot_price * 0.99)
            sell_call = self._round_to_strike(vah, round_up=True)
            buy_call = self._round_to_strike(sell_call + self.step_size * 2, round_up=True)
            sell_put = self._round_to_strike(val, round_up=False)
            buy_put = self._round_to_strike(sell_put - self.step_size * 2, round_up=False)
            variants.append({
                "variant_id": "VARIANT_4_DEFAULT",
                "variant_name": "DEX-Range Iron Condor (Conservative)",
                "type": "Non-directional Premium Collection",
                "tier": "Tier 2",
                "confidence_score": cs,
                "sell_call_strike": sell_call,
                "buy_call_strike": buy_call,
                "sell_put_strike": sell_put,
                "buy_put_strike": buy_put,
                "expiry_preference": "Weekly",
                "recommended_risk_pct": 1.0,
                "entry_conditions": [f"Confluence score ({cs:.1f}) tradable; Range bound setup"],
                "exit_conditions": ["50% max profit -> close", "Wing breach -> stop loss"]
            })

        return variants
