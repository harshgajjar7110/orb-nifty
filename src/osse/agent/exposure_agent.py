"""
Dhan Exposure Agent for OSSE.

Orchestrates the end-to-end flow:
  1. Navigate to a user-supplied Dhan Dext URL via Kimi WebBridge.
  2. Extract Delta Exposure and Gamma Exposure from the dashboard.
  3. Build DEX/GEX metric dicts directly from the parsed GreeksExposure
     totals and levels (no secondary option-chain fetch required).
  4. Drive StrikeSelector with the GEX_DEX_ALIGNED variant and return
     a trade-ready strike recommendation.

WebBridge is the only supported collector.  If the daemon is unreachable
the agent returns an ERROR result immediately.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from osse.data.greeks_parser import GreeksExposure, GreeksParser
from osse.data.webbridge_collector import WebBridgeCollector
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
        })


class DhanExposureAgent:
    """
    End-to-end agent for Dhan Dext exposure-driven strike selection.

    Requires the Kimi WebBridge daemon to be running.  No MCP fallback.
    """

    DEFAULT_DAEMON_URL = "http://127.0.0.1:10086"
    DEFAULT_SYMBOL = "NIFTY"

    def __init__(
        self,
        daemon_url: Optional[str] = None,
        session: str = "osse-exposure",
    ):
        self.daemon_url = daemon_url or self.DEFAULT_DAEMON_URL
        self.session = session
        self.webbridge = WebBridgeCollector(
            daemon_url=self.daemon_url, session=self.session
        )

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
        Returns ERROR immediately if the WebBridge daemon is unreachable.
        """
        result = ExposureAgentResult(url=url, symbol=symbol)

        # 1. Verify WebBridge daemon is reachable
        if not self.webbridge.ensure_daemon():
            result.status = "ERROR"
            result.reason = (
                "Kimi WebBridge daemon is not reachable at "
                f"{self.daemon_url}. Start it with: "
                "kimi-webbridge start"
            )
            return result

        result.collector_used = "webbridge"

        # 2. Fetch Delta + Gamma exposure via WebBridge
        try:
            delta_ge, gamma_ge = self._fetch_via_webbridge(url, symbol)
            result.delta_exposure = delta_ge
            result.gamma_exposure = gamma_ge
            result.spot_price = (
                delta_ge.spot_price
                if delta_ge.spot_price and delta_ge.spot_price > 0
                else gamma_ge.spot_price
            )
        except Exception as e:
            logger.error(f"[ExposureAgent] WebBridge fetch failed: {e}")
            result.status = "ERROR"
            result.reason = f"WebBridge fetch failed: {e}"
            return result

        if not result.spot_price or result.spot_price <= 0:
            result.status = "ERROR"
            result.reason = "Could not determine spot price from exposure data."
            return result

        # 3. Build DEX / GEX dicts directly from parsed GreeksExposure
        result.dex_data = self._build_dex_dict(delta_ge)
        result.gex_data = self._build_gex_dict(gamma_ge)

        # 4. Fetch option chain for leg pricing, then run strike selection
        try:
            chain = self._get_option_chain(symbol, result.spot_price)
            selector = StrikeSelector()
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
    # WebBridge fetch
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
    # DEX / GEX dict builders (from parsed GreeksExposure)
    # ------------------------------------------------------------------
    def _build_dex_dict(self, ge: GreeksExposure) -> Dict[str, Any]:
        """
        Builds a DEX metrics dict directly from a parsed GreeksExposure
        object.  No secondary option-chain computation required.
        """
        levels = ge.levels or {}
        return {
            "status": "SUCCESS",
            "total_call_dex": ge.total_call,
            "total_put_dex": ge.total_put,
            "total_net_dex": ge.total_net,
            "dex_ratio": ge.ratio,
            "call_wall": (levels.get("call_resistance") or {}).get("strike"),
            "put_support": (levels.get("put_support") or {}).get("strike"),
            "delta_flip": (levels.get("flip") or {}).get("strike"),
        }

    def _build_gex_dict(self, ge: GreeksExposure) -> Dict[str, Any]:
        """
        Builds a GEX metrics dict directly from a parsed GreeksExposure
        object.  No secondary option-chain computation required.
        """
        levels = ge.levels or {}
        return {
            "status": "SUCCESS",
            "total_call_gex": ge.total_call,
            "total_put_gex": ge.total_put,
            "total_net_gex": ge.total_net,
            "peak_pos_gamma_strike": (levels.get("peak_positive") or {}).get("strike"),
            "peak_neg_gamma_strike": (levels.get("peak_negative") or {}).get("strike"),
            "gamma_flip": (levels.get("flip") or {}).get("strike"),
        }

    # ------------------------------------------------------------------
    # Option chain for leg pricing
    # ------------------------------------------------------------------
    def _get_option_chain(self, symbol: str, spot_price: float) -> Dict[str, Any]:
        """
        Returns the dict-style option chain consumed by StrikeSelector.
        Uses DataCollector (Dhan API → yfinance → synthetic BS) so the
        selector always has real or synthetic premiums for leg pricing.
        Exposure levels (DEX/GEX) drive strike placement regardless of
        whether the chain is live.
        """
        from osse.data.collector import DataCollector

        try:
            chain = DataCollector.fetch_option_chain(symbol=symbol)
            if chain and chain.get("chain"):
                return chain
        except Exception as e:
            logger.warning(f"[ExposureAgent] Live chain fetch failed: {e}; using synthetic.")

        return DataCollector.generate_synthetic_option_chain(
            spot_price, symbol, vix=15.0, strike_depth=20
        )
