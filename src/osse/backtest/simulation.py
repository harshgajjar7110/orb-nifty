"""
Unified Trade Simulation & Stop-Loss Module for OSSE Backtesting and Dashboard.
"""

from typing import Dict, Any, Optional
import pandas as pd


def simulate_trade(
    intraday_df: pd.DataFrame,
    orb_stats: Dict[str, Any],
    decision: Dict[str, Any],
    sl_buffer_pct: float = 0.001,
    use_trailing_sl: bool = False,
    trailing_step_pct: float = 0.005,
    score: float = 50.0
) -> Dict[str, Any]:
    """
    Simulates intraday breakout trade execution tick-by-tick with configurable stop-loss buffer
    and optional trailing stop-loss logic.

    :param intraday_df: 1-min OHLCV dataframe
    :param orb_stats: ORB metrics dictionary containing orb_high, orb_low
    :param decision: Decision dictionary with decision status
    :param sl_buffer_pct: Stop loss buffer percentage (default 0.001 = 0.1%)
    :param use_trailing_sl: Enable trailing stop loss logic
    :param trailing_step_pct: Trailing SL distance percentage (default 0.005 = 0.5%)
    :param score: OSSE score (0-100); bullish if >= 50, bearish if < 50
    :return: Decision dictionary updated with MFE, MAE, trade_pnl, and execution details
    """
    if decision.get("decision") not in ["TRADE", "REDUCED SIZE"]:
        return decision

    trade_data = intraday_df.between_time("09:30", "15:15")
    if trade_data.empty:
        return decision

    orb_high = float(orb_stats["orb_high"])
    orb_low = float(orb_stats["orb_low"])
    entry_price = 0.0
    direction = 0  # 1 for Long breakout, -1 for Short breakdown

    high_col = "High" if "High" in trade_data.columns else "high"
    low_col = "Low" if "Low" in trade_data.columns else "low"
    close_col = "Close" if "Close" in trade_data.columns else "close"

    is_bullish = score >= 50.0

    # Find breakout entry bar aligned with score direction
    entry_idx_name = None
    for idx, row in trade_data.iterrows():
        if row[high_col] > orb_high and is_bullish:
            entry_price = orb_high
            direction = 1
            entry_idx_name = idx
            break
        elif row[low_col] < orb_low and not is_bullish:
            entry_price = orb_low
            direction = -1
            entry_idx_name = idx
            break

    if direction == 0 or entry_idx_name is None:
        return decision

    entry_idx = trade_data.index.get_loc(entry_idx_name)
    post_entry_data = trade_data.iloc[entry_idx:]

    # Calculate Initial Stop Loss
    if direction == 1:
        current_sl = orb_low * (1.0 - sl_buffer_pct)
    else:
        current_sl = orb_high * (1.0 + sl_buffer_pct)

    max_high = entry_price
    min_low = entry_price
    exit_price = entry_price
    sl_hit = False

    for p_idx, p_row in post_entry_data.iterrows():
        curr_high = float(p_row[high_col])
        curr_low = float(p_row[low_col])
        curr_close = float(p_row[close_col])

        max_high = max(max_high, curr_high)
        min_low = min(min_low, curr_low)

        # Dynamic Trailing SL update
        if use_trailing_sl:
            if direction == 1:
                potential_sl = curr_high * (1.0 - trailing_step_pct)
                if potential_sl > current_sl:
                    current_sl = potential_sl
            else:
                potential_sl = curr_low * (1.0 + trailing_step_pct)
                if potential_sl < current_sl:
                    current_sl = potential_sl

        # Check Stop Loss trigger
        if direction == 1 and curr_low <= current_sl:
            exit_price = current_sl
            sl_hit = True
            break
        elif direction == -1 and curr_high >= current_sl:
            exit_price = current_sl
            sl_hit = True
            break

        exit_price = curr_close

    if direction == 1:
        decision["mfe"] = max_high - entry_price
        decision["mae"] = entry_price - min_low
        decision["trade_pnl"] = exit_price - entry_price
    else:
        decision["mfe"] = entry_price - min_low
        decision["mae"] = max_high - entry_price
        decision["trade_pnl"] = entry_price - exit_price

    decision["entry_price"] = entry_price
    decision["exit_price"] = exit_price
    decision["stop_loss"] = current_sl
    decision["sl_hit"] = sl_hit
    decision["direction"] = "LONG" if direction == 1 else "SHORT"

    return decision
