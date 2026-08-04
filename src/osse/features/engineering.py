import pandas as pd
import logging
import numpy as np
import math

logger = logging.getLogger(__name__)

def _sanitize_float(value, default=0.0):
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default

class FeatureEngineering:
    """
    Generates the final feature set for the scoring engine (FR-007).
    Extracts raw numerical features that will be normalized later.
    """

    @staticmethod
    def extract_features(intraday_df: pd.DataFrame, orb_stats: dict, daily_context: dict, orb_window_mins: int = 15) -> dict:
        """
        Combines indicator data and ORB stats into a raw feature dictionary.
        
        :param intraday_df: DataFrame with indicators calculated
        :param orb_stats: ORB statistics from ORBBuilder
        :param daily_context: Daily context (prev close, etc)
        :param orb_window_mins: Minutes for the ORB window (15 or 30)
        :return: Raw features for scoring
        """
        try:
            logger.info("Extracting quantitative features from indicators and ORB stats...")
            end_time = '09:29' if orb_window_mins == 15 else '09:44'
            orb_slice = intraday_df.between_time('09:15', end_time)
            if orb_slice.empty:
                logger.warning(f"Empty intraday slice between 09:15 and {end_time}. Returning default feature dictionary.")
                return {
                    'orb_width': 0.0,
                    'relative_volume': 1.0,
                    'vwap_distance': 0.0,
                    'ema_alignment': 0.0,
                    'atr_expansion': 0.0,
                    'adx': 0.0,
                    'gap_percent': 0.0,
                    'candle_efficiency': 0.0,
                    'trend_consistency': 0.0,
                    'opening_momentum': 0.0,
                    'iv_rank': daily_context.get('iv_rank', 50.0),
                    'vix': daily_context.get('vix', 15.0),
                    'cpr_width': daily_context.get('cpr_width', 0.5),
                    'htf_alignment': 0.5
                }
            
            orb_end_candle = orb_slice.iloc[-1]
            
            features = {}
            
            # 1. ORB Width % (Numeric)
            features['orb_width'] = _sanitize_float(orb_stats.get('orb_percent', 0.0))
            
            # 2. Relative Volume (Numeric)
            daily_vol = daily_context.get('daily_volume', 1)
            expected_orb_vol = daily_vol * (orb_window_mins / 375.0)
            orb_volume = orb_stats.get('orb_volume', 0)
            if expected_orb_vol > 0 and orb_volume > 0:
                features['relative_volume'] = _sanitize_float(orb_volume / expected_orb_vol, 1.0)
            else:
                atr_14 = orb_end_candle.get('ATR_14', 1.0)
                atr_14 = _sanitize_float(atr_14, 1.0)
                orb_width_val = orb_stats.get('orb_width', 0)
                orb_width_val = _sanitize_float(orb_width_val, 0.0)
                if atr_14 > 0:
                    atr_exp = orb_width_val / atr_14
                else:
                    atr_exp = 1.0
                features['relative_volume'] = _sanitize_float(max(1.0, min(2.5, atr_exp)), 1.0)
            
            # 3. VWAP Distance (Numeric)
            vwap_raw = orb_end_candle.get('VWAP', None)
            if vwap_raw is None or (isinstance(vwap_raw, float) and (math.isnan(vwap_raw) or math.isinf(vwap_raw))):
                vwap_raw = orb_end_candle.get('Close', 0)
            close_val = orb_end_candle.get('Close', 0)
            vwap_val = _sanitize_float(vwap_raw, 0.0)
            close_val = _sanitize_float(close_val, 0.0)
            if vwap_val > 0 and close_val > 0:
                vwap_dist = abs(close_val - vwap_val) / vwap_val
            else:
                vwap_dist = 0.0
            features['vwap_distance'] = _sanitize_float(vwap_dist * 100, 0.0)

            # 4. EMA Alignment (Numeric)
            ema20 = _sanitize_float(orb_end_candle.get('EMA_20', 0), 0.0)
            ema50 = _sanitize_float(orb_end_candle.get('EMA_50', 0), 0.0)
            close_for_ema = _sanitize_float(orb_end_candle.get('Close', 0), 0.0)
            
            alignment = 0.0
            if close_for_ema > ema20 > ema50:
                alignment = 1.0
            elif close_for_ema < ema20 < ema50:
                alignment = 1.0
            elif (close_for_ema > ema20 and ema20 < ema50) or (close_for_ema < ema20 and ema20 > ema50):
                alignment = 0.5
            
            features['ema_alignment'] = alignment

            # 5. ATR Expansion (Numeric)
            atr_14 = _sanitize_float(orb_end_candle.get('ATR_14', 1.0), 1.0)
            orb_width_val = _sanitize_float(orb_stats.get('orb_width', 0.0), 0.0)
            features['atr_expansion'] = _sanitize_float(orb_width_val / atr_14 if atr_14 > 0 else 0.0, 0.0)
            
            # 6. ADX (Numeric)
            features['adx'] = _sanitize_float(orb_end_candle.get('ADX_14', 0.0), 0.0)
            
            # 7. Gap % (Numeric)
            prev_close = daily_context.get('prev_close', orb_end_candle.get('Open', 0))
            prev_close = _sanitize_float(prev_close, 0.0)
            first_open = _sanitize_float(orb_slice.iloc[0].get('Open', 0), 0.0)
            features['gap_percent'] = _sanitize_float(abs(first_open - prev_close) / prev_close * 100 if prev_close > 0 else 0.0, 0.0)

            # 8. Candle Efficiency (Numeric)
            features['candle_efficiency'] = _sanitize_float(orb_stats.get('candle_efficiency', 0.0), 0.0)
            
            # 9. Trend Consistency (Numeric) - RSI usage here
            rsi = _sanitize_float(orb_end_candle.get('RSI_14', 50), 50)
            features['trend_consistency'] = _sanitize_float(abs(rsi - 50) / 50.0, 0.0)

            # 10. Opening Momentum (Numeric)
            first_open = _sanitize_float(orb_slice.iloc[0].get('Open', 0), 0.0)
            features['opening_momentum'] = _sanitize_float((abs(close_val - first_open) / first_open) * 100.0 if first_open > 0 else 0.0, 0.0)

            # 11. IV Rank & VIX Context
            features['iv_rank'] = _sanitize_float(daily_context.get('iv_rank', 50.0), 50.0)
            features['vix'] = _sanitize_float(daily_context.get('vix', 15.0), 15.0)

            # 12. CPR Metrics
            features['cpr_width'] = _sanitize_float(daily_context.get('cpr_width', 0.5), 0.5)

            # 13. Higher Timeframe Alignment (HTF Alignment)
            daily_trend = daily_context.get('daily_trend', 1.0)
            vwap_diff_pct = (abs(close_val - vwap_val) / vwap_val) * 100.0 if vwap_val > 0 else 0.0
            
            if (close_val >= vwap_val and daily_trend >= 0) or (close_val <= vwap_val and daily_trend < 0):
                features['htf_alignment'] = 1.0
            elif vwap_diff_pct <= 0.15:
                features['htf_alignment'] = 0.5
            else:
                features['htf_alignment'] = 0.0

            return features
             
        except Exception as e:
            logger.error(f"Error extracting features: {str(e)}")
            raise

    @staticmethod
    def detect_regime(features: dict, daily_context: dict = None) -> str:
        """
        Detects the broad market regime tailored for Directional vs Option Selling strategies.
        """
        adx = features.get('adx', 0)
        gap = features.get('gap_percent', 0)
        iv_rank = features.get('iv_rank', 50)
        htf_align = features.get('htf_alignment', 0.5)
        
        if gap > 0.6:
            return "GAP"
        elif adx >= 22 and htf_align == 1.0:
            return "DIRECTIONAL_BREAKOUT"
        elif adx < 20 and iv_rank >= 40:
            return "PREMIUM_SELL_RANGE"
        elif adx > 25:
            return "TRENDING"
        elif adx < 20:
            return "RANGING"
        else:
            return "NEUTRAL"

