"""
Volume Profile 70% (Value Area) Feature Calculator for OSSE.

Computes Point of Control (POC), Value Area High (VAH), Value Area Low (VAL),
High Volume Nodes (HVN), Low Volume Nodes (LVN), and Volume Delta.
"""

from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd


class VolumeProfileCalculator:
    """
    Histogram-based 70% Value Area & Volume Profile Engine.
    """

    def __init__(self, va_percent: float = 0.70, num_bins: int = 50):
        self.va_percent = va_percent
        self.num_bins = num_bins

    def calculate_volume_profile(
        self,
        df: pd.DataFrame,
        va_percent: Optional[float] = None,
        num_bins: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Calculates VP metrics from intraday candle data.

        Expected DataFrame columns:
            - high or High
            - low or Low
            - close or Close
            - open or Open (optional)
            - volume or Volume
        """
        if df is None or df.empty:
            return self._empty_response("Empty candles dataframe.")

        effective_va_pct = va_percent or self.va_percent
        effective_num_bins = num_bins or self.num_bins

        # Normalize column names
        col_map = {col.lower(): col for col in df.columns}
        high_col = col_map.get("high")
        low_col = col_map.get("low")
        close_col = col_map.get("close")
        open_col = col_map.get("open")
        vol_col = col_map.get("volume") or col_map.get("vol")

        if not all([high_col, low_col, close_col, vol_col]):
            return self._empty_response("Missing required OHLCV columns.")

        prices_high = df[high_col].astype(float).values
        prices_low = df[low_col].astype(float).values
        prices_close = df[close_col].astype(float).values
        prices_open = df[open_col].astype(float).values if open_col else prices_close
        volumes = df[vol_col].astype(float).values

        total_volume = float(np.sum(volumes))
        if total_volume <= 0:
            return self._empty_response("Total volume is zero.")

        min_price = float(np.min(prices_low))
        max_price = float(np.max(prices_high))

        if min_price == max_price:
            return {
                "status": "SUCCESS",
                "poc": min_price,
                "vah": max_price,
                "val": min_price,
                "hvn_array": [min_price],
                "lvn_array": [],
                "total_volume": total_volume,
                "volume_delta": 0.0,
                "profile_bins": []
            }

        # Create price bin edges and centers
        bin_edges = np.linspace(min_price, max_price, effective_num_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        bin_volumes = np.zeros(effective_num_bins)
        bin_vol_delta = np.zeros(effective_num_bins)

        # Distribute volume across bins spanning [low, high] for each candle
        for h, l, c, o, v in zip(prices_high, prices_low, prices_close, prices_open, volumes):
            # Buying vs selling volume approximation
            v_delta = v if c >= o else -v
            
            # Bins overlapped by candle
            bin_idx = np.where((bin_edges[:-1] <= h) & (bin_edges[1:] >= l))[0]
            if len(bin_idx) > 0:
                vol_per_bin = v / len(bin_idx)
                delta_per_bin = v_delta / len(bin_idx)
                for idx in bin_idx:
                    bin_volumes[idx] += vol_per_bin
                    bin_vol_delta[idx] += delta_per_bin
            else:
                # Fallback to close price bin
                idx = min(int((c - min_price) / (max_price - min_price) * effective_num_bins), effective_num_bins - 1)
                bin_volumes[idx] += v
                bin_vol_delta[idx] += v_delta

        # Point of Control (POC): bin with maximum volume
        poc_idx = int(np.argmax(bin_volumes))
        poc = float(bin_centers[poc_idx])

        # 70% Value Area Extraction around POC
        target_va_volume = total_volume * effective_va_pct
        accumulated_vol = bin_volumes[poc_idx]
        included_bins = {poc_idx}

        low_idx = poc_idx - 1
        high_idx = poc_idx + 1

        while accumulated_vol < target_va_volume and (low_idx >= 0 or high_idx < effective_num_bins):
            vol_below = bin_volumes[low_idx] if low_idx >= 0 else 0.0
            vol_above = bin_volumes[high_idx] if high_idx < effective_num_bins else 0.0

            if vol_below >= vol_above and low_idx >= 0:
                accumulated_vol += vol_below
                included_bins.add(low_idx)
                low_idx -= 1
            elif high_idx < effective_num_bins:
                accumulated_vol += vol_above
                included_bins.add(high_idx)
                high_idx += 1
            elif low_idx >= 0:
                accumulated_vol += vol_below
                included_bins.add(low_idx)
                low_idx -= 1

        va_bins = sorted(list(included_bins))
        val = float(bin_edges[va_bins[0]])
        vah = float(bin_edges[va_bins[-1] + 1])

        # HVN (> mean + 0.5 * std) and LVN (< mean - 0.5 * std)
        vol_mean = np.mean(bin_volumes)
        vol_std = np.std(bin_volumes)
        
        hvn_mask = bin_volumes > (vol_mean + 0.5 * vol_std)
        lvn_mask = bin_volumes < max(vol_mean - 0.5 * vol_std, 0.1 * vol_mean)

        hvn_array = [float(p) for p in bin_centers[hvn_mask]]
        lvn_array = [float(p) for p in bin_centers[lvn_mask]]

        total_vol_delta = float(np.sum(bin_vol_delta))

        bins_summary = [
            {
                "price": float(bin_centers[i]),
                "volume": float(bin_volumes[i]),
                "volume_delta": float(bin_vol_delta[i]),
                "in_value_area": i in included_bins
            }
            for i in range(effective_num_bins)
        ]

        return {
            "status": "SUCCESS",
            "poc": poc,
            "vah": vah,
            "val": val,
            "hvn_array": hvn_array,
            "lvn_array": lvn_array,
            "total_volume": total_volume,
            "volume_delta": total_vol_delta,
            "profile_bins": bins_summary
        }

    def _empty_response(self, reason: str = "Empty data") -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "reason": reason,
            "poc": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "hvn_array": [],
            "lvn_array": [],
            "total_volume": 0.0,
            "volume_delta": 0.0,
            "profile_bins": []
        }
