"""
Delta Exposure (DEX) Calculator for OSSE.

Calculates aggregate dealer delta exposure per strike across option chains
to identify Call Walls, Put Supports, Delta Flip levels, and DEX Clusters.
"""

from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd


class DEXCalculator:
    """
    Computes DEX metrics per strike and identifies institutional dealer positioning boundaries.
    """

    def __init__(self, default_lot_size: int = 75):
        self.default_lot_size = default_lot_size

    def calculate_dex(
        self,
        option_chain: pd.DataFrame,
        lot_size: Optional[int] = None,
        spot_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates Net DEX, Call Wall, Put Support, Delta Flip, and Clusters from option chain data.

        Expected DataFrame columns:
            - strike_price (float)
            - ce_oi (float)
            - ce_delta (float)
            - pe_oi (float)
            - pe_delta (float)
        """
        if option_chain is None or option_chain.empty:
            return self._empty_response()

        df = option_chain.copy()
        effective_lot_size = lot_size or self.default_lot_size

        # Required columns check with case-insensitive fallback
        col_map = {col.lower(): col for col in df.columns}
        
        strike_col = col_map.get("strike_price") or col_map.get("strike")
        ce_oi_col = col_map.get("ce_oi") or col_map.get("call_oi") or col_map.get("ce_open_interest")
        ce_delta_col = col_map.get("ce_delta") or col_map.get("call_delta")
        pe_oi_col = col_map.get("pe_oi") or col_map.get("put_oi") or col_map.get("pe_open_interest")
        pe_delta_col = col_map.get("pe_delta") or col_map.get("put_delta")

        if not all([strike_col, ce_oi_col, ce_delta_col, pe_oi_col, pe_delta_col]):
            return self._empty_response(reason="Missing required option chain columns for DEX calculation.")

        df = df.sort_values(by=strike_col).reset_index(drop=True)
        
        # Calculate CE DEX, PE DEX, Net DEX
        df["ce_dex"] = df[ce_oi_col].fillna(0) * df[ce_delta_col].fillna(0) * effective_lot_size
        df["pe_dex"] = df[pe_oi_col].fillna(0) * df[pe_delta_col].fillna(0) * effective_lot_size
        df["net_dex"] = df["ce_dex"] + df["pe_dex"]

        # Call Wall: Strike with maximum CE DEX
        call_wall_idx = df["ce_dex"].idxmax()
        call_wall = float(df.loc[call_wall_idx, strike_col]) if not pd.isna(call_wall_idx) else 0.0
        max_ce_dex = float(df.loc[call_wall_idx, "ce_dex"]) if not pd.isna(call_wall_idx) else 0.0

        # Put Support: Strike with maximum negative PE DEX (most negative)
        put_support_idx = df["pe_dex"].idxmin()
        put_support = float(df.loc[put_support_idx, strike_col]) if not pd.isna(put_support_idx) else 0.0
        max_pe_dex = float(df.loc[put_support_idx, "pe_dex"]) if not pd.isna(put_support_idx) else 0.0

        # Delta Flip: Strike where Net DEX changes sign (zero crossing)
        net_dex_arr = df["net_dex"].values
        strikes = df[strike_col].values
        
        delta_flip = None # default to None if no sign change
        sign_changes = np.where(np.diff(np.signbit(net_dex_arr)))[0]
        
        if len(sign_changes) > 0:
            if spot_price and spot_price > 0:
                # Pick sign change closest to spot price
                closest_idx = sign_changes[np.argmin(np.abs(strikes[sign_changes] - spot_price))]
                delta_flip = float(strikes[closest_idx])
            else:
                delta_flip = float(strikes[sign_changes[0]])
        elif spot_price and spot_price > 0:
            delta_flip = spot_price

        # DEX Clusters: strikes with |net_dex| > 50% of max |net_dex|
        abs_net_dex = np.abs(net_dex_arr)
        max_abs_dex = np.max(abs_net_dex) if len(abs_net_dex) > 0 else 0.0
        
        cluster_mask = abs_net_dex >= (0.5 * max_abs_dex) if max_abs_dex > 0 else np.zeros_like(abs_net_dex, dtype=bool)
        dex_clusters = [float(s) for s in strikes[cluster_mask]]

        dex_table = df[[strike_col, "ce_dex", "pe_dex", "net_dex"]].to_dict(orient="records")

        total_ce_dex = float(np.sum(df["ce_dex"].values))
        total_pe_dex = float(np.sum(df["pe_dex"].values))
        total_net_dex = float(np.sum(net_dex_arr))

        # DEX ratio: put-side magnitude vs call-side magnitude.
        # Values > 1 suggest put-heavy positioning (supportive/bullish
        # contrarian), values < 1 suggest call-heavy positioning.
        dex_ratio = round(abs(total_pe_dex) / total_ce_dex, 4) if total_ce_dex != 0 else 0.0

        return {
            "status": "SUCCESS",
            "call_wall": call_wall,
            "max_ce_dex": max_ce_dex,
            "put_support": put_support,
            "max_pe_dex": max_pe_dex,
            "delta_flip": delta_flip,
            "dex_clusters": dex_clusters,
            "lot_size": effective_lot_size,
            "strike_dex_table": dex_table,
            "total_net_dex": total_net_dex,
            "total_call_dex": total_ce_dex,
            "total_put_dex": total_pe_dex,
            "dex_ratio": dex_ratio,
        }

    def _empty_response(self, reason: str = "Empty data") -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "reason": reason,
            "call_wall": 0.0,
            "max_ce_dex": 0.0,
            "put_support": 0.0,
            "max_pe_dex": 0.0,
            "delta_flip": 0.0,
            "dex_clusters": [],
            "lot_size": self.default_lot_size,
            "strike_dex_table": [],
            "total_net_dex": 0.0,
            "total_call_dex": 0.0,
            "total_put_dex": 0.0,
            "dex_ratio": 0.0,
        }
