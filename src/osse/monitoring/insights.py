"""
Insights Generator for the OSSE Live Monitor.

Turns the latest option-chain + candle snapshot into:
  - signal_alerts: actionable threshold-crossing alerts
  - summary_report: human-readable market snapshot
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
import os
import yaml

import pandas as pd
import numpy as np

from osse.engine.dex_calculator import DEXCalculator
from osse.features.volume_profile import VolumeProfileCalculator
from osse.engine.confluence import ConfluenceEngine
from osse.engine.strategy_variants import StrategyVariantSelector
from osse.engine.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class InsightsGenerator:
    """
    Generates signal alerts and summary reports from live market snapshots.
    """

    def __init__(self, osse_score: float = 50.0):
        self.osse_score = osse_score

    @staticmethod
    def _pcr_from_chain(chain_df: pd.DataFrame) -> float:
        """Computes Put/Call OI ratio from the option chain."""
        if chain_df is None or chain_df.empty:
            return 1.0
        pe_oi = chain_df.get("pe_oi", pd.Series(dtype=float)).sum()
        ce_oi = chain_df.get("ce_oi", pd.Series(dtype=float)).sum()
        if ce_oi <= 0:
            return 1.0
        return float(pe_oi / ce_oi)

    @staticmethod
    def _total_oi(chain_df: pd.DataFrame) -> float:
        if chain_df is None or chain_df.empty:
            return 0.0
        pe_oi = chain_df.get("pe_oi", pd.Series(dtype=float)).sum()
        ce_oi = chain_df.get("ce_oi", pd.Series(dtype=float)).sum()
        return float(pe_oi + ce_oi)

    def generate_insights(
        self,
        symbol: str,
        spot_price: float,
        chain_df: pd.DataFrame,
        candles_df: pd.DataFrame,
        osse_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Runs DEX + VP + Confluence + Variants and produces alerts + summary.
        """
        osse_score = osse_score if osse_score is not None else self.osse_score
        
        # Load symbol configurations from strike_rules.yaml dynamically
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        rules_path = os.path.join(base_dir, "config", "strike_rules.yaml")
        symbols_cfg = {}
        if os.path.exists(rules_path):
            try:
                with open(rules_path, "r") as f:
                    symbols_cfg = yaml.safe_load(f).get("symbols", {})
            except Exception:
                pass
                
        sym_upper = symbol.upper()
        sym_rules = symbols_cfg.get(sym_upper, symbols_cfg.get("DEFAULT_STOCK", {"step_size": 50, "lot_size": 75}))
        step_size = float(sym_rules.get("step_size", 50.0))
        lot_size = int(sym_rules.get("lot_size", 75))

        # Run quantitative engines
        dex_res = DEXCalculator(default_lot_size=lot_size).calculate_dex(chain_df, spot_price=spot_price)
        vp_res = VolumeProfileCalculator().calculate_volume_profile(candles_df)
        conf_engine = ConfluenceEngine(step_size=step_size)
        conf_res = conf_engine.calculate_confluence_score(
            dex_data=dex_res,
            vp_data=vp_res,
            spot_price=spot_price
        )
        unified_res = conf_engine.calculate_unified_score(
            osse_score=osse_score,
            confluence_score=conf_res.get("confluence_score", 0.0)
        )

        # Pick a representative VIX for variant selection
        vix = 15.0
        if chain_df is not None and not chain_df.empty:
            ce_iv = chain_df.get("ce_iv", pd.Series(dtype=float))
            pe_iv = chain_df.get("pe_iv", pd.Series(dtype=float))
            if not ce_iv.empty and ce_iv.notna().any():
                vix = float(ce_iv.mean())
            elif not pe_iv.empty and pe_iv.notna().any():
                vix = float(pe_iv.mean())

        pcr = self._pcr_from_chain(chain_df)
        orb_width_pct = 0.5  # Placeholder; monitor does not compute ORB live

        variants = StrategyVariantSelector(symbol=symbol, step_size=step_size).select_variants(
            spot_price=spot_price,
            confluence_data=conf_res,
            dex_data=dex_res,
            vp_data=vp_res,
            osse_score=osse_score,
            vix=vix,
            pcr_oi=pcr,
            orb_width_pct=orb_width_pct
        )

        # Risk snapshot
        risk_mgr = RiskManager()
        risk_snapshot = risk_mgr.calculate_position_size(
            capital=1_000_000.0,
            risk_percent=2.0,
            max_loss_per_lot=15000.0
        )

        # Build summary report
        summary_report = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "spot_price": spot_price,
            "osse_score": osse_score,
            "vix": vix,
            "pcr_oi": pcr,
            "total_oi": self._total_oi(chain_df),
            "dex": {
                "call_wall": dex_res.get("call_wall"),
                "put_support": dex_res.get("put_support"),
                "delta_flip": dex_res.get("delta_flip"),
                "total_net_dex": dex_res.get("total_net_dex"),
                "status": dex_res.get("status")
            },
            "volume_profile": {
                "poc": vp_res.get("poc"),
                "vah": vp_res.get("vah"),
                "val": vp_res.get("val"),
                "status": vp_res.get("status")
            },
            "confluence": conf_res,
            "unified_score": unified_res,
            "variants": variants[:3],
            "risk_snapshot": risk_snapshot
        }

        # Build signal alerts
        signal_alerts = self._build_alerts(
            symbol=symbol,
            spot_price=spot_price,
            dex_res=dex_res,
            vp_res=vp_res,
            conf_res=conf_res,
            unified_res=unified_res,
            pcr=pcr,
            vix=vix
        )

        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "signal_alerts": signal_alerts,
            "summary_report": summary_report
        }

    def _build_alerts(
        self,
        symbol: str,
        spot_price: float,
        dex_res: Dict[str, Any],
        vp_res: Dict[str, Any],
        conf_res: Dict[str, Any],
        unified_res: Dict[str, Any],
        pcr: float,
        vix: float
    ) -> List[Dict[str, Any]]:
        alerts = []
        cs = conf_res.get("confluence_score", 0.0)
        us = unified_res.get("unified_score", 0.0)

        if cs >= 80:
            alerts.append({
                "level": "HIGH",
                "type": "CONFLUENCE_TIER1",
                "message": f"{symbol}: Tier 1 confluence ({cs:.1f}). Favor primary non-directional setups."
            })
        elif cs >= 60:
            alerts.append({
                "level": "MEDIUM",
                "type": "CONFLUENCE_TIER2",
                "message": f"{symbol}: Tier 2 confluence ({cs:.1f}). Reduce size and be selective."
            })

        if us >= 85:
            alerts.append({
                "level": "HIGH",
                "type": "UNIFIED_TIER1",
                "message": f"{symbol}: Unified score {us:.1f} — full-size setup if risk limits allow."
            })
        elif us < 45:
            alerts.append({
                "level": "LOW",
                "type": "NO_TRADE",
                "message": f"{symbol}: Unified score {us:.1f} — skip new entries."
            })

        call_wall = dex_res.get("call_wall", 0.0)
        put_support = dex_res.get("put_support", 0.0)

        if call_wall > 0 and spot_price > 0:
            dist = abs(spot_price - call_wall) / spot_price
            if dist <= 0.003:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "NEAR_CALL_WALL",
                    "message": f"{symbol}: Spot {spot_price:.2f} is within 0.3% of Call Wall {call_wall:.2f}."
                })

        if put_support > 0 and spot_price > 0:
            dist = abs(spot_price - put_support) / spot_price
            if dist <= 0.003:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "NEAR_PUT_SUPPORT",
                    "message": f"{symbol}: Spot {spot_price:.2f} is within 0.3% of Put Support {put_support:.2f}."
                })

        if pcr > 1.2:
            alerts.append({
                "level": "MEDIUM",
                "type": "PCR_BULLISH",
                "message": f"{symbol}: PCR {pcr:.2f} elevated — put writing dominance / mildly bullish contrarian."
            })
        elif pcr < 0.8:
            alerts.append({
                "level": "MEDIUM",
                "type": "PCR_BEARISH",
                "message": f"{symbol}: PCR {pcr:.2f} low — call writing dominance / mildly bearish contrarian."
            })

        if vix > 22.0:
            alerts.append({
                "level": "MEDIUM",
                "type": "VIX_ELEVATED",
                "message": f"{symbol}: IV/VIX {vix:.1f} elevated — widen strikes or reduce size."
            })
        elif vix < 12.0:
            alerts.append({
                "level": "LOW",
                "type": "VIX_LOW",
                "message": f"{symbol}: IV/VIX {vix:.1f} low — premium collection less attractive."
            })

        vah = vp_res.get("vah", 0.0)
        val = vp_res.get("val", 0.0)
        if vah > 0 and val > 0 and spot_price > 0:
            if spot_price > vah:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "ABOVE_VAH",
                    "message": f"{symbol}: Spot above Value Area High ({vah:.2f}) — momentum/extension bias."
                })
            elif spot_price < val:
                alerts.append({
                    "level": "MEDIUM",
                    "type": "BELOW_VAL",
                    "message": f"{symbol}: Spot below Value Area Low ({val:.2f}) — weakness/extension bias."
                })

        return alerts
