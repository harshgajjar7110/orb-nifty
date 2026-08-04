"""
Gamma Exposure (GEX) Calculator for OSSE.

Calculates aggregate dealer gamma exposure per strike across option chains
to identify Gamma Flip, Peak +Gamma (call resistance) and Peak -Gamma
(put support) levels.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


class GammaExposureCalculator:
    """
    Computes GEX metrics per strike and identifies gamma-driven boundaries.
    """

    def __init__(self, default_lot_size: int = 75):
        self.default_lot_size = default_lot_size

    def calculate_gex(
        self,
        option_chain: pd.DataFrame,
        lot_size: Optional[int] = None,
        spot_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculates Net GEX, Gamma Flip, Peak +/- Gamma from option chain data.

        Expected DataFrame columns:
            - strike_price (float)
            - ce_oi (float)
            - ce_gamma (float, optional)
            - pe_oi (float)
            - pe_gamma (float, optional)

        If gamma columns are missing they are estimated using Black-Scholes.
        """
        if option_chain is None or option_chain.empty:
            return self._empty_response()

        df = option_chain.copy()
        effective_lot_size = lot_size or self.default_lot_size

        col_map = {col.lower(): col for col in df.columns}
        strike_col = col_map.get("strike_price") or col_map.get("strike")
        ce_oi_col = col_map.get("ce_oi") or col_map.get("call_oi")
        pe_oi_col = col_map.get("pe_oi") or col_map.get("put_oi")
        ce_gamma_col = col_map.get("ce_gamma") or col_map.get("call_gamma")
        pe_gamma_col = col_map.get("pe_gamma") or col_map.get("put_gamma")

        if not all([strike_col, ce_oi_col, pe_oi_col]):
            return self._empty_response(reason="Missing required option chain columns for GEX calculation.")

        df = df.sort_values(by=strike_col).reset_index(drop=True)

        # Compute gamma if not supplied
        if not ce_gamma_col or not pe_gamma_col:
            df = self._compute_missing_gamma(df, spot_price)
            col_map = {col.lower(): col for col in df.columns}
            ce_gamma_col = col_map.get("ce_gamma") or col_map.get("call_gamma")
            pe_gamma_col = col_map.get("pe_gamma") or col_map.get("put_gamma")
            if not ce_gamma_col or not pe_gamma_col:
                return self._empty_response(reason="Could not derive gamma values.")

        # Per-strike GEX (gamma * OI * lot_size). Gamma is positive for both CE and PE.
        df["ce_gex"] = df[ce_oi_col].fillna(0) * df[ce_gamma_col].fillna(0) * effective_lot_size
        df["pe_gex"] = df[pe_oi_col].fillna(0) * df[pe_gamma_col].fillna(0) * effective_lot_size
        df["net_gex"] = df["ce_gex"] + df["pe_gex"]

        # Peak +Gamma (call resistance / max net GEX)
        peak_pos_idx = df["net_gex"].idxmax()
        peak_pos_strike = float(df.loc[peak_pos_idx, strike_col]) if not pd.isna(peak_pos_idx) else 0.0
        max_gex = float(df.loc[peak_pos_idx, "net_gex"]) if not pd.isna(peak_pos_idx) else 0.0

        # Peak -Gamma (put support / most negative net GEX)
        peak_neg_idx = df["net_gex"].idxmin()
        peak_neg_strike = float(df.loc[peak_neg_idx, strike_col]) if not pd.isna(peak_neg_idx) else 0.0
        min_gex = float(df.loc[peak_neg_idx, "net_gex"]) if not pd.isna(peak_neg_idx) else 0.0

        # Gamma Flip: zero crossing of Net GEX closest to spot
        net_gex_arr = df["net_gex"].values
        strikes = df[strike_col].values
        gamma_flip = None
        sign_changes = np.where(np.diff(np.signbit(net_gex_arr)))[0]
        if len(sign_changes) > 0:
            if spot_price and spot_price > 0:
                closest_idx = sign_changes[np.argmin(np.abs(strikes[sign_changes] - spot_price))]
                gamma_flip = float(strikes[closest_idx])
            else:
                gamma_flip = float(strikes[sign_changes[0]])
        elif spot_price and spot_price > 0:
            gamma_flip = spot_price

        # Clusters: strikes with |net_gex| > 50% of max |net_gex|
        abs_net_gex = np.abs(net_gex_arr)
        max_abs_gex = np.max(abs_net_gex) if len(abs_net_gex) > 0 else 0.0
        cluster_mask = (
            abs_net_gex >= (0.5 * max_abs_gex)
            if max_abs_gex > 0
            else np.zeros_like(abs_net_gex, dtype=bool)
        )
        gex_clusters = [float(s) for s in strikes[cluster_mask]]

        gex_table = df[[strike_col, "ce_gex", "pe_gex", "net_gex"]].to_dict(orient="records")

        return {
            "status": "SUCCESS",
            "peak_pos_gamma_strike": peak_pos_strike,
            "max_gex": max_gex,
            "peak_neg_gamma_strike": peak_neg_strike,
            "min_gex": min_gex,
            "gamma_flip": gamma_flip,
            "gex_clusters": gex_clusters,
            "lot_size": effective_lot_size,
            "strike_gex_table": gex_table,
            "total_call_gex": float(np.sum(df["ce_gex"].values)),
            "total_put_gex": float(np.sum(df["pe_gex"].values)),
            "total_net_gex": float(np.sum(net_gex_arr)),
        }

    def _compute_missing_gamma(
        self,
        df: pd.DataFrame,
        spot_price: Optional[float],
    ) -> pd.DataFrame:
        """
        Computes CE/PE gamma via Black-Scholes when the scraped chain does not
        include them.  Uses IV columns if present, otherwise a flat 15% IV.
        """
        df = df.copy()
        col_map = {col.lower(): col for col in df.columns}
        strike_col = col_map.get("strike_price") or col_map.get("strike")

        try:
            from osse.options.expiry_manager import ExpiryManager
            from datetime import datetime

            expiry_info = ExpiryManager.calculate_all_expiries(datetime.now().strftime("%Y-%m-%d"), "NIFTY")
            dte = expiry_info.get("WEEKLY", {}).get("dte_days", 7)
            T = max(1 / 365.0, dte / 365.0)
        except Exception:
            T = 7 / 365.0

        r = 0.065
        spot = spot_price if spot_price and spot_price > 0 else df[strike_col].median()

        from osse.options.synthetic_pricing import BlackScholesEngine

        if "ce_gamma" not in df.columns and "call_gamma" not in df.columns:
            ce_iv_col = col_map.get("ce_iv") or col_map.get("call_iv")
            df["ce_gamma"] = df.apply(
                lambda row: BlackScholesEngine.calculate_greeks(
                    S=spot,
                    K=float(row[strike_col]),
                    T=T,
                    r=r,
                    sigma=(
                        float(row[ce_iv_col]) / 100.0
                        if ce_iv_col and float(row.get(ce_iv_col, 0) or 0) > 0
                        else 0.15
                    ),
                    option_type="CE",
                )["gamma"],
                axis=1,
            )

        if "pe_gamma" not in df.columns and "put_gamma" not in df.columns:
            pe_iv_col = col_map.get("pe_iv") or col_map.get("put_iv")
            df["pe_gamma"] = df.apply(
                lambda row: BlackScholesEngine.calculate_greeks(
                    S=spot,
                    K=float(row[strike_col]),
                    T=T,
                    r=r,
                    sigma=(
                        float(row[pe_iv_col]) / 100.0
                        if pe_iv_col and float(row.get(pe_iv_col, 0) or 0) > 0
                        else 0.16
                    ),
                    option_type="PE",
                )["gamma"],
                axis=1,
            )

        return df

    def _empty_response(self, reason: str = "Empty data") -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "reason": reason,
            "peak_pos_gamma_strike": 0.0,
            "max_gex": 0.0,
            "peak_neg_gamma_strike": 0.0,
            "min_gex": 0.0,
            "gamma_flip": 0.0,
            "gex_clusters": [],
            "lot_size": self.default_lot_size,
            "strike_gex_table": [],
            "total_call_gex": 0.0,
            "total_put_gex": 0.0,
            "total_net_gex": 0.0,
        }
