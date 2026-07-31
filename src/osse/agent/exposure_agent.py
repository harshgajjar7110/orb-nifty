"""
Dhan Exposure Agent for OSSE.

Orchestrates the end-to-end flow:
  1. Navigate to a user-supplied Dhan Dext URL via Kimi WebBridge.
  2. Extract Delta Exposure and Gamma Exposure from the dashboard.
  3. Compute DEX/GEX metrics and drive the StrikeSelector with the
     GEX_DEX_ALIGNED variant.
  4. Return a trade-ready strike recommendation.

The agent prefers WebBridge (real browser, user's login session) and falls
back to the existing DhanMCPCollector if the WebBridge daemon is unreachable.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from osse.data.dhan_mcp import DhanMCPCollector
from osse.data.greeks_parser import GreeksExposure, GreeksParser
from osse.data.webbridge_collector import WebBridgeCollector
from osse.engine.dex_calculator import DEXCalculator
from osse.engine.gamma_calculator import GammaExposureCalculator
from osse.options.strike_selector import StrikeSelector

logger = logging.getLogger(__name__)


@dataclass
class ExposureAgentResult:
    """Structured output of the Dhan Exposure Agent."""

    status: str = "ERROR"
    reason: str = ""
    url: str = ""
    symbol: str = ""
    spot_price: Optional[float] = None
    delta_exposure: Optional[GreeksExposure] = None
    gamma_exposure: Optional[GreeksExposure] = None
    dex_data: Dict[str, Any] = field(default_factory=dict)
    gex_data: Dict[str, Any] = field(default_factory=dict)
    strike_recommendation: Dict[str, Any] = field(default_factory=dict)
    collector_used: str = ""
    fallback_reason: str = ""

    @staticmethod
    def _jsonify(obj: Any) -> Any:
        """Recursively converts numpy/pandas types to JSON-serializable natives."""
        if isinstance(obj, (np.bool_, np.bool)):
            return bool(obj)
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        if isinstance(obj, dict):
            return {k: ExposureAgentResult._jsonify(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ExposureAgentResult._jsonify(v) for v in obj]
        return obj

    def to_dict(self) -> Dict[str, Any]:
        return self._jsonify({
            "status": self.status,
            "reason": self.reason,
            "url": self.url,
            "symbol": self.symbol,
            "spot_price": self.spot_price,
            "delta_exposure": self.delta_exposure.to_dict() if self.delta_exposure else None,
            "gamma_exposure": self.gamma_exposure.to_dict() if self.gamma_exposure else None,
            "dex_data": self.dex_data,
            "gex_data": self.gex_data,
            "strike_recommendation": self.strike_recommendation,
            "collector_used": self.collector_used,
            "fallback_reason": self.fallback_reason,
        })


class DhanExposureAgent:
    """
    End-to-end agent for Dhan Dext exposure-driven strike selection.
    """

    DEFAULT_DAEMON_URL = "http://127.0.0.1:10086"
    DEFAULT_SYMBOL = "NIFTY"

    def __init__(
        self,
        daemon_url: Optional[str] = None,
        session: str = "osse-exposure",
        use_mcp_fallback: bool = True,
    ):
        self.daemon_url = daemon_url or self.DEFAULT_DAEMON_URL
        self.session = session
        self.use_mcp_fallback = use_mcp_fallback
        self.webbridge = WebBridgeCollector(
            daemon_url=self.daemon_url, session=self.session
        )
        self.mcp_collector: Optional[DhanMCPCollector] = None
        if use_mcp_fallback:
            self.mcp_collector = DhanMCPCollector()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        url: str,
        strategy_name: str = "Directional Credit Spread",
        direction: str = "UP",
        symbol: str = DEFAULT_SYMBOL,
        variant: str = "GEX_DEX_ALIGNED",
        expiry_type: str = "WEEKLY",
    ) -> ExposureAgentResult:
        """
        Executes the full exposure-driven strike selection workflow.
        """
        result = ExposureAgentResult(url=url, symbol=symbol)

        # 1. Choose collector
        collector_used, fallback_reason = self._choose_collector()
        result.collector_used = collector_used
        result.fallback_reason = fallback_reason

        if collector_used == "webbridge":
            try:
                delta_ge, gamma_ge = self._fetch_via_webbridge(url, symbol)
                result.delta_exposure = delta_ge
                result.gamma_exposure = gamma_ge
                result.spot_price = delta_ge.spot_price or gamma_ge.spot_price
            except Exception as e:
                logger.warning(f"[ExposureAgent] WebBridge fetch failed: {e}")
                if not self.use_mcp_fallback:
                    result.status = "ERROR"
                    result.reason = f"WebBridge fetch failed and fallback disabled: {e}"
                    return result
                collector_used = "dhan_mcp"
                result.collector_used = collector_used
                result.fallback_reason = f"WebBridge error: {e}"

        if collector_used == "dhan_mcp":
            delta_ge, gamma_ge = self._fetch_via_mcp(symbol)
            result.delta_exposure = delta_ge
            result.gamma_exposure = gamma_ge
            result.spot_price = delta_ge.spot_price or gamma_ge.spot_price

        if result.spot_price is None or result.spot_price <= 0:
            result.status = "ERROR"
            result.reason = "Could not determine spot price from exposure data."
            return result

        # 2. Compute DEX / GEX
        result.dex_data = self._compute_dex(symbol, result.spot_price)
        result.gex_data = self._compute_gex(symbol, result.spot_price)

        # 3. Override DEX/GEX key levels with scraped parser levels when available
        self._merge_parser_levels(result)

        # 4. Generate strike recommendation
        try:
            selector = StrikeSelector()
            chain = self._get_option_chain(symbol, result.spot_price)
            rec = selector.select_strikes(
                strategy_name=strategy_name,
                spot_price=result.spot_price,
                option_chain=chain,
                symbol=symbol,
                variant=variant,
                expiry_type=expiry_type,
                direction=direction,
                dex_data=result.dex_data,
                gex_data=result.gex_data,
            )
            result.strike_recommendation = rec
            result.status = "SUCCESS"
        except Exception as e:
            logger.error(f"[ExposureAgent] Strike selection failed: {e}")
            result.status = "ERROR"
            result.reason = f"Strike selection failed: {e}"

        return result

    # ------------------------------------------------------------------
    # Collector selection
    # ------------------------------------------------------------------
    def _choose_collector(self) -> tuple:
        """Returns (collector_name, fallback_reason)."""
        if self.webbridge.ensure_daemon():
            return "webbridge", ""
        if not self.use_mcp_fallback:
            return "webbridge", "WebBridge daemon unreachable; fallback disabled"
        return "dhan_mcp", "WebBridge daemon unreachable; using DhanMCPCollector fallback"

    # ------------------------------------------------------------------
    # WebBridge path
    # ------------------------------------------------------------------
    def _fetch_via_webbridge(
        self, url: str, symbol: str
    ) -> tuple[GreeksExposure, GreeksExposure]:
        """Navigates to the Dhan Dext dashboard and extracts Delta + Gamma."""
        logger.info(f"[ExposureAgent] Navigating to {url}")
        nav_resp = self.webbridge.navigate(
            url=url, new_tab=True, group_title="OSSE Dhan Exposure"
        )
        if not nav_resp.get("success"):
            raise RuntimeError(f"Navigation failed: {nav_resp.get('error')}")

        # Delta tab
        if not self.webbridge.find_tab_and_click("Delta Exposure"):
            logger.warning("[ExposureAgent] Could not click Delta Exposure tab")
        delta_snap = self.webbridge.snapshot()
        delta_texts = self.webbridge.flatten_snapshot_text(delta_snap)
        delta_ge = GreeksParser.parse_snapshot_text(
            delta_texts, exposure_type="delta", symbol_hint=symbol
        )

        # Gamma tab
        if not self.webbridge.find_tab_and_click("Gamma Exposure"):
            logger.warning("[ExposureAgent] Could not click Gamma Exposure tab")
        gamma_snap = self.webbridge.snapshot()
        gamma_texts = self.webbridge.flatten_snapshot_text(gamma_snap)
        gamma_ge = GreeksParser.parse_snapshot_text(
            gamma_texts, exposure_type="gamma", symbol_hint=symbol
        )

        return delta_ge, gamma_ge

    # ------------------------------------------------------------------
    # MCP fallback path
    # ------------------------------------------------------------------
    def _fetch_via_mcp(self, symbol: str) -> tuple[GreeksExposure, GreeksExposure]:
        """Builds GreeksExposure objects from the DhanMCPCollector option chain."""
        if self.mcp_collector is None:
            raise RuntimeError("DhanMCPCollector fallback not initialized")

        chain_df = self.mcp_collector.fetch_option_chain(symbol=symbol)
        spot = chain_df["strike_price"].median() if not chain_df.empty else 0.0

        delta_ge = GreeksExposure(exposure_type="delta", symbol=symbol, spot_price=spot)
        gamma_ge = GreeksExposure(exposure_type="gamma", symbol=symbol, spot_price=spot)

        if chain_df.empty:
            return delta_ge, gamma_ge

        dex_calc = DEXCalculator()
        gex_calc = GammaExposureCalculator()
        dex_res = dex_calc.calculate_dex(chain_df, spot_price=spot)
        gex_res = gex_calc.calculate_gex(chain_df, spot_price=spot)

        if dex_res.get("status") == "SUCCESS":
            delta_ge.total_call = dex_res.get("total_call_dex")
            delta_ge.total_put = dex_res.get("total_put_dex")
            delta_ge.total_net = dex_res.get("total_net_dex")
            delta_ge.ratio = dex_res.get("dex_ratio")
            delta_ge.levels = {
                "call_resistance": {"strike": dex_res.get("call_wall")},
                "put_support": {"strike": dex_res.get("put_support")},
                "flip": {"strike": dex_res.get("delta_flip")},
            }

        if gex_res.get("status") == "SUCCESS":
            gamma_ge.total_call = gex_res.get("total_call_gex")
            gamma_ge.total_put = gex_res.get("total_put_gex")
            gamma_ge.total_net = gex_res.get("total_net_gex")
            gamma_ge.levels = {
                "peak_positive": {"strike": gex_res.get("peak_pos_gamma_strike")},
                "peak_negative": {"strike": gex_res.get("peak_neg_gamma_strike")},
                "flip": {"strike": gex_res.get("gamma_flip")},
            }

        return delta_ge, gamma_ge

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------
    def _compute_dex(self, symbol: str, spot_price: float) -> Dict[str, Any]:
        """Computes DEX from the option chain."""
        chain_df = self._get_chain_df(symbol, spot_price)
        return DEXCalculator().calculate_dex(chain_df, spot_price=spot_price)

    def _compute_gex(self, symbol: str, spot_price: float) -> Dict[str, Any]:
        """Computes GEX from the option chain."""
        chain_df = self._get_chain_df(symbol, spot_price)
        return GammaExposureCalculator().calculate_gex(chain_df, spot_price=spot_price)

    def _get_chain_df(self, symbol: str, spot_price: float) -> pd.DataFrame:
        """Returns a DataFrame option chain, preferring MCP data."""
        if self.mcp_collector is not None:
            try:
                return self.mcp_collector.fetch_option_chain(symbol=symbol)
            except Exception as e:
                logger.warning(f"[ExposureAgent] MCP chain fetch failed: {e}")
        # Fallback to synthetic chain
        from osse.data.collector import DataCollector

        chain = DataCollector.generate_synthetic_option_chain(
            spot_price, symbol, vix=15.0, strike_depth=20
        )
        rows = []
        for item in chain.get("chain", []):
            rows.append(
                {
                    "strike_price": item["strike"],
                    "ce_oi": item["ce"].get("oi", 0),
                    "ce_delta": item["ce"].get("delta", 0.0),
                    "ce_gamma": item["ce"].get("gamma", 0.0),
                    "pe_oi": item["pe"].get("oi", 0),
                    "pe_delta": item["pe"].get("delta", 0.0),
                    "pe_gamma": item["pe"].get("gamma", 0.0),
                }
            )
        return pd.DataFrame(rows)

    def _get_option_chain(self, symbol: str, spot_price: float) -> Dict[str, Any]:
        """Returns the dict-style option chain used by StrikeSelector."""
        # StrikeSelector consumes a chain dict.  We generate a synthetic chain
        # around the scraped spot price; exposure levels (DEX/GEX) drive the
        # final strike selection regardless of whether the chain is live.
        from osse.data.collector import DataCollector

        return DataCollector.generate_synthetic_option_chain(
            spot_price, symbol, vix=15.0, strike_depth=20
        )

    # ------------------------------------------------------------------
    # Level merging
    # ------------------------------------------------------------------
    def _merge_parser_levels(self, result: ExposureAgentResult) -> None:
        """Overwrites computed DEX/GEX levels with parsed dashboard levels."""
        if result.delta_exposure and result.delta_exposure.levels:
            levels = result.delta_exposure.levels
            if "call_resistance" in levels:
                result.dex_data["call_wall"] = levels["call_resistance"].get("strike")
            if "put_support" in levels:
                result.dex_data["put_support"] = levels["put_support"].get("strike")
            if "flip" in levels:
                result.dex_data["delta_flip"] = levels["flip"].get("strike")

        if result.gamma_exposure and result.gamma_exposure.levels:
            levels = result.gamma_exposure.levels
            if "peak_positive" in levels:
                result.gex_data["peak_pos_gamma_strike"] = levels["peak_positive"].get(
                    "strike"
                )
            if "peak_negative" in levels:
                result.gex_data["peak_neg_gamma_strike"] = levels["peak_negative"].get(
                    "strike"
                )
            if "flip" in levels:
                result.gex_data["gamma_flip"] = levels["flip"].get("strike")
