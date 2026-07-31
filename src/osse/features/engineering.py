import pandas as pd
import logging
import numpy as np

logger = logging.getLogger(__name__)

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
            # We take the state of indicators at exactly the breakout time
            end_time = '09:29' if orb_window_mins == 15 else '09:44'
            orb_end_candle = intraday_df.between_time('09:15', end_time).iloc[-1]
            
            features = {}
            
            # 1. ORB Width % (Numeric)
            features['orb_width'] = orb_stats.get('orb_percent', 0.0)
            
            # 2. Relative Volume (Numeric)
            # Current ORB Volume / Daily Average Volume (or a fraction thereof)
            # Alternatively, compare to rolling volume in historic database
            daily_vol = daily_context.get('daily_volume', 1)
            # Assuming ORB volume should be compared to a fraction of daily volume (e.g., 15 mins out of 375 mins)
            expected_orb_vol = daily_vol * (orb_window_mins / 375.0)
            if expected_orb_vol > 0 and orb_stats.get('orb_volume', 0) > 0:
                features['relative_volume'] = orb_stats.get('orb_volume', 0) / expected_orb_vol
            else:
                # Index Fallback: When volume is 0, use ATR expansion ratio as relative activity proxy
                atr_14 = orb_end_candle.get('ATR_14', 1.0)
                atr_exp = orb_stats.get('orb_width', 0) / atr_14 if atr_14 > 0 else 1.0
                features['relative_volume'] = max(1.0, min(2.5, atr_exp))
            
            # 3. VWAP Distance (Numeric)
            vwap = orb_end_candle.get('VWAP', orb_end_candle['Close'])
            vwap_dist = (abs(orb_end_candle['Close'] - vwap) / vwap) if vwap > 0 else 0.0
            features['vwap_distance'] = vwap_dist * 100 # percentage

            # 4. EMA Alignment (Numeric)
            # Basic check: Is Close > EMA20 > EMA50?
            ema20 = orb_end_candle.get('EMA_20', 0)
            ema50 = orb_end_candle.get('EMA_50', 0)
            close = orb_end_candle['Close']
            
            alignment = 0.0
            if close > ema20 > ema50:
                alignment = 1.0 # Strong uptrend alignment
            elif close < ema20 < ema50:
                alignment = 1.0 # Strong downtrend alignment
            elif (close > ema20 and ema20 < ema50) or (close < ema20 and ema20 > ema50):
                alignment = 0.5 # Partial alignment
            
            features['ema_alignment'] = alignment

            # 5. ATR Expansion (Numeric)
            atr_14 = orb_end_candle.get('ATR_14', 1.0)
            features['atr_expansion'] = orb_stats.get('orb_width', 0) / atr_14 if atr_14 > 0 else 0.0
            
            # 6. ADX (Numeric)
            features['adx'] = orb_end_candle.get('ADX_14', 0.0)
            
            # 7. Gap % (Numeric)
            prev_close = daily_context.get('prev_close', orb_end_candle['Open'])
            open_price = intraday_df.between_time('09:15', end_time).iloc[0]['Open']
            features['gap_percent'] = abs(open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

            # 8. Candle Efficiency (Numeric)
            features['candle_efficiency'] = orb_stats.get('candle_efficiency', 0.0)
            
            # 9. Trend Consistency (Numeric) - RSI usage here
            rsi = orb_end_candle.get('RSI_14', 50)
            # Normalized RSI distance from 50
            features['trend_consistency'] = abs(rsi - 50) / 50.0

            # 10. Opening Momentum (Numeric)
            first_open = intraday_df.between_time('09:15', end_time).iloc[0]['Open']
            features['opening_momentum'] = (abs(close - first_open) / first_open) * 100.0 if first_open > 0 else 0.0

            # 11. IV Rank & VIX Context
            features['iv_rank'] = daily_context.get('iv_rank', 50.0)
            features['vix'] = daily_context.get('vix', 15.0)

            # 12. CPR Metrics
            features['cpr_width'] = daily_context.get('cpr_width', 0.5)

            # 13. Higher Timeframe Alignment (HTF Alignment)
            daily_trend = daily_context.get('daily_trend', 1.0)
            vwap_diff_pct = (abs(close - vwap) / vwap) * 100.0 if vwap > 0 else 0.0
            
            if (close >= vwap and daily_trend >= 0) or (close <= vwap and daily_trend < 0):
                features['htf_alignment'] = 1.0  # Fully aligned
            elif vwap_diff_pct <= 0.15:
                features['htf_alignment'] = 0.5  # Neutral consolidation at VWAP
            else:
                features['htf_alignment'] = 0.0  # Conflicting trend

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

