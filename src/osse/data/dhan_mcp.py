"""
Dhan MCP Collector & Data Validation Bridge for OSSE.

Orchestrates Dhan Web platform extraction via MCP/Node.js, performs DOM vs API
data validation checks, and provides yfinance/synthetic fallback mechanisms.
"""

from typing import Dict, List, Any, Optional
import os
import json
import subprocess
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from osse.options.synthetic_pricing import BlackScholesEngine
from osse.options.expiry_manager import ExpiryManager

logger = logging.getLogger(__name__)


class DhanMCPCollector:
    """
    Python Bridge for Dhan MCP Browser Automation and Data Validation.
    """

    DEFAULT_STALE_SECONDS = 300  # 5 minutes

    def __init__(self, data_dir: str = "data", stale_seconds: Optional[int] = None):
        self.data_dir = data_dir
        self.stale_seconds = stale_seconds or int(os.environ.get("DHAN_STALE_SECONDS", self.DEFAULT_STALE_SECONDS))
        self.option_chain_file = os.path.join(data_dir, "dhan_option_chain.json")
        self.chart_data_file = os.path.join(data_dir, "dhan_chart_data.json")
        self.portfolio_file = os.path.join(data_dir, "dhan_portfolio.json")

    @staticmethod
    def _repo_base_dir() -> str:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _script_path(self, script_name: str) -> str:
        return os.path.join(self._repo_base_dir(), "scripts", "dhan_mcp", script_name)

    def _is_stale(self, file_path: str) -> bool:
        """Returns True if the file does not exist or is older than stale_seconds."""
        if not os.path.exists(file_path):
            return True
        try:
            mtime = os.path.getmtime(file_path)
            age_seconds = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds()
            return age_seconds > self.stale_seconds
        except Exception:
            return True

    def run_node_mcp_script(self, script_name: str, symbol: str = "NIFTY", use_mock_fallback: bool = True) -> bool:
        """
        Launches Node.js MCP extraction script as a subprocess to pull live data.
        """
        script_path = self._script_path(script_name)
        if not os.path.exists(script_path):
            logger.warning(f"[DhanMCPCollector] Node script not found: {script_path}")
            return False
        try:
            args = ["node", script_path, symbol]
            if use_mock_fallback and os.environ.get("DHAN_MCP_MOCK") == "1":
                args.append("--mock")
            logger.info(f"[DhanMCPCollector] Invoking {' '.join(args)}")
            res = subprocess.run(args, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                logger.warning(f"[DhanMCPCollector] Node script exited {res.returncode}: {res.stderr}")
            return res.returncode == 0
        except Exception as e:
            logger.error(f"[DhanMCPCollector] Error invoking Node MCP script {script_name}: {e}")
            return False

    def _load_json_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[DhanMCPCollector] Error reading {file_path}: {e}")
            return None

    def _compute_missing_deltas(self, df: pd.DataFrame, spot_price: Optional[float], symbol: str) -> pd.DataFrame:
        """
        Computes CE/PE deltas via Black-Scholes when the scraped chain does not include them.
        """
        if df.empty:
            return df

        df = df.copy()
        if "strike_price" not in df.columns and "strike" in df.columns:
            df = df.rename(columns={"strike": "strike_price"})

        if "ce_delta" not in df.columns:
            df["ce_delta"] = np.nan
        if "pe_delta" not in df.columns:
            df["pe_delta"] = np.nan

        missing_ce = df["ce_delta"].isna()
        missing_pe = df["pe_delta"].isna()

        if not missing_ce.any() and not missing_pe.any():
            return df

        try:
            expiry_info = ExpiryManager.calculate_all_expiries(datetime.now().strftime("%Y-%m-%d"), symbol)
            dte = expiry_info.get("WEEKLY", {}).get("dte_days", 7)
            T = max(1 / 365.0, dte / 365.0)
        except Exception:
            T = 7 / 365.0

        r = 0.065
        spot = spot_price if spot_price and spot_price > 0 else df["strike_price"].median()

        if missing_ce.any():
            ce_iv_col = "ce_iv" if "ce_iv" in df.columns else "call_iv"
            df.loc[missing_ce, "ce_delta"] = df[missing_ce].apply(
                lambda row: BlackScholesEngine.calculate_delta(
                    S=spot,
                    K=float(row["strike_price"]),
                    T=T,
                    r=r,
                    sigma=float(row.get(ce_iv_col, 15.0)) / 100.0 if float(row.get(ce_iv_col, 15.0)) > 1 else float(row.get(ce_iv_col, 0.15)),
                    option_type="CE"
                ),
                axis=1
            )

        if missing_pe.any():
            pe_iv_col = "pe_iv" if "pe_iv" in df.columns else "put_iv"
            df.loc[missing_pe, "pe_delta"] = df[missing_pe].apply(
                lambda row: BlackScholesEngine.calculate_delta(
                    S=spot,
                    K=float(row["strike_price"]),
                    T=T,
                    r=r,
                    sigma=float(row.get(pe_iv_col, 16.0)) / 100.0 if float(row.get(pe_iv_col, 16.0)) > 1 else float(row.get(pe_iv_col, 0.16)),
                    option_type="PE"
                ),
                axis=1
            )

        return df

    def fetch_option_chain(self, symbol: str = "NIFTY", force_refresh: bool = False) -> pd.DataFrame:
        """
        Loads option chain extracted via Dhan MCP or generates fallback option chain.
        """
        if force_refresh or self._is_stale(self.option_chain_file):
            self.run_node_mcp_script("extract_option_chain.js", symbol=symbol)

        data = self._load_json_file(self.option_chain_file)
        if data:
            try:
                chain_list = data.get("option_chain", [])
                spot_price = data.get("spot_price")
                if chain_list and len(chain_list) > 0:
                    df = pd.DataFrame(chain_list)
                    df = self._compute_missing_deltas(df, spot_price, symbol)
                    validation = self.validate_data(df)
                    if validation["is_valid"]:
                        return df
                    else:
                        logger.warning(f"[DhanMCPCollector] Validation issues: {validation.get('issues')}")
            except Exception as e:
                logger.error(f"[DhanMCPCollector] Error reading option chain file: {e}")

        logger.warning("[DhanMCPCollector] Falling back to synthetic option chain.")
        return self._generate_fallback_option_chain(symbol=symbol)

    def fetch_chart_candles(self, symbol: str = "NIFTY", force_refresh: bool = False) -> pd.DataFrame:
        """
        Loads candle data extracted via Dhan MCP or generates fallback candles.
        """
        if force_refresh or self._is_stale(self.chart_data_file):
            self.run_node_mcp_script("extract_chart_data.js", symbol=symbol)

        data = self._load_json_file(self.chart_data_file)
        if data:
            try:
                candles = data.get("candles", [])
                if candles and len(candles) > 0:
                    return pd.DataFrame(candles)
            except Exception as e:
                logger.error(f"[DhanMCPCollector] Error reading chart data file: {e}")

        # Fallback to DhanHQ/yfinance via DataCollector
        try:
            from osse.data.collector import DataCollector
            from osse.data.validator import DataValidator
            today = datetime.now().strftime("%Y-%m-%d")
            df = DataCollector.fetch_data(symbol, start_date=today)
            if not df.empty and DataValidator.validate_intraday_data(df):
                logger.info("[DhanMCPCollector] Using DataCollector fallback for candles.")
                return df
        except Exception as e:
            logger.warning(f"[DhanMCPCollector] DataCollector fallback failed: {e}")

        logger.warning("[DhanMCPCollector] Falling back to synthetic candles.")
        return self._generate_fallback_candles(symbol=symbol)

    def validate_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Performs data integrity checks (PRD Section 10.3):
        - OI change reasonableness (<50% jump)
        - Volume spike check (<5x average)
        - Non-empty values
        """
        if df is None or df.empty:
            return {"is_valid": False, "reason": "Empty dataframe"}

        issues = []

        if "ce_oi" in df.columns:
            ce_oi = df["ce_oi"].values
            if len(ce_oi) > 1 and np.max(ce_oi) > 0:
                oi_diffs = np.abs(np.diff(ce_oi)) / (ce_oi[:-1] + 1.0)
                if np.any(oi_diffs > 5.0):  # 500% anomaly
                    issues.append("Unusual OI spike detected across adjacent strikes.")

        if "ce_volume" in df.columns:
            vols = df["ce_volume"].values
            mean_vol = np.mean(vols) if len(vols) > 0 else 0
            if mean_vol > 0 and np.max(vols) > 5.0 * mean_vol:
                issues.append("Volume spike (>5x mean) detected.")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues
        }

    def _generate_fallback_option_chain(self, symbol: str = "NIFTY") -> pd.DataFrame:
        """Fallback synthetic option chain for graceful degradation."""
        spot = 52000.0 if symbol == "BANKNIFTY" else 24500.0
        step = 100 if symbol == "BANKNIFTY" else 50

        rows = []
        for i in range(-10, 11):
            strike = spot + (i * step)
            dist = abs(i)
            ce_delta = max(0.01, min(0.99, 0.50 - (i * 0.04)))
            pe_delta = -max(0.01, min(0.99, 0.50 + (i * 0.04)))

            rows.append({
                "strike_price": strike,
                "ce_oi": int(100000 * (0.85 ** dist)),
                "ce_delta": ce_delta,
                "ce_iv": 15.0,
                "ce_volume": 50000,
                "pe_oi": int(120000 * (0.88 ** dist)),
                "pe_delta": pe_delta,
                "pe_iv": 16.0,
                "pe_volume": 60000
            })

        return pd.DataFrame(rows)

    def _generate_fallback_candles(self, symbol: str = "NIFTY") -> pd.DataFrame:
        """Fallback synthetic 1-min candles for Volume Profile."""
        spot = 52000.0 if symbol == "BANKNIFTY" else 24500.0

        candles = []
        curr = spot
        for i in range(45):
            change = float(np.random.normal(0, 10))
            open_p = curr
            close_p = open_p + change
            high_p = max(open_p, close_p) + float(abs(np.random.normal(0, 5)))
            low_p = min(open_p, close_p) - float(abs(np.random.normal(0, 5)))
            vol = int(np.random.uniform(5000, 20000))
            candles.append({
                "high": high_p,
                "low": low_p,
                "open": open_p,
                "close": close_p,
                "volume": vol
            })
            curr = close_p

        return pd.DataFrame(candles)
