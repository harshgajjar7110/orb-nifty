import os
import yaml
import logging

logger = logging.getLogger(__name__)

class DecisionEngine:
    """
    Translates the numerical score into a discrete trade action (FR-010, FR-011).
    Thresholds are loaded from config/scoring_rules.yaml.
    """

    _config = None
    _thresholds = None

    @staticmethod
    def _load_config():
        if DecisionEngine._config is not None:
            return DecisionEngine._config
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        config_path = os.path.join(base_dir, 'config', 'scoring_rules.yaml')
        try:
            with open(config_path, 'r') as f:
                DecisionEngine._config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load scoring config: {e}")
            DecisionEngine._config = {}
        return DecisionEngine._config

    @staticmethod
    def _get_thresholds():
        if DecisionEngine._thresholds is not None:
            return DecisionEngine._thresholds
        config = DecisionEngine._load_config()
        DecisionEngine._thresholds = config.get('decision_thresholds', {})
        return DecisionEngine._thresholds

    @staticmethod
    def get_strategy_recommendation(score: float, regime: str = "NEUTRAL", iv_rank: float = 50.0) -> str:
        """
        Provides specific Intraday trade strategy recommendations based on OSSE score, market regime, and IV Rank.
        All strategies are strictly designed for Intraday execution (MIS - Exit by 15:15 PM IST).
        """
        if score >= 75:
            if iv_rank >= 50:
                return "Intraday Directional Credit Spread"
            else:
                return "Intraday Directional Momentum (Debit Spread)"
        elif score >= 60:
            if regime == "PREMIUM_SELL_RANGE" or iv_rank >= 50:
                return "Intraday Iron Condor / Short Strangle"
            else:
                return "Intraday Directional Credit Spread (Reduced Sizing)"
        elif regime == "PREMIUM_SELL_RANGE" and iv_rank >= 40:
            return "Intraday Short Straddle / Iron Fly"
        else:
            return "No Trade / Avoid (Low Intraday Edge)"

    @staticmethod
    def get_decision(
        score: float,
        regime: str = "NEUTRAL",
        iv_rank: float = 50.0,
        spot_price: float = None,
        option_chain: dict = None,
        daily_context: dict = None,
        symbol: str = "NIFTY"
    ) -> dict:
        """
        Interprets score and returns confidence, decision, and strategy recommendation.
        """
        thresholds = DecisionEngine._get_thresholds()
        strategy = DecisionEngine.get_strategy_recommendation(score, regime, iv_rank)

        trade_threshold = thresholds.get("TRADE", {}).get("min_score", 65)
        reduced_threshold = thresholds.get("REDUCED_SIZE", {}).get("min_score", 55)
        weak_threshold = thresholds.get("NO_TRADE_WEAK", {}).get("min_score", 45)

        if score >= trade_threshold:
            res = {"confidence": "High", "decision": "TRADE", "recommended_strategy": strategy}
        elif score >= reduced_threshold:
            res = {"confidence": "Tradable", "decision": "REDUCED SIZE", "recommended_strategy": strategy}
        elif score >= weak_threshold:
            res = {"confidence": "Weak", "decision": "NO TRADE", "recommended_strategy": strategy}
        else:
            res = {"confidence": "Reject", "decision": "NO TRADE", "recommended_strategy": strategy}

        return res

    @staticmethod
    def generate_pros_cons(score: float, regime: str, raw_features: dict, daily_context: dict, recommended_strategy: str = "") -> tuple[list[str], list[str]]:
        """
        Generates strategy-aware Pros and Cons for the setup, calibrating OSSE score, IV Rank,
        ADX trend momentum, CPR width, and VWAP extension based on strategy context.
        """
        pros = []
        cons = []

        is_selling_strategy = any(term in recommended_strategy for term in ["Credit", "Sell", "Iron Condor", "Straddle", "Strangle", "Iron Fly"])
        is_buying_strategy = any(term in recommended_strategy for term in ["Debit", "Long Futures", "Breakout Swing"])
        is_range_strategy = any(term in recommended_strategy for term in ["Iron Condor", "Straddle", "Strangle", "Iron Fly"])

        # 1. OSSE Score Evaluation (Aligned with DecisionEngine tiers)
        if score >= 70:
            pros.append(f"High OSSE Score ({score:.1f}/100) confirms strong statistical breakout momentum.")
        elif 55 <= score < 70:
            pros.append(f"Moderate OSSE Score ({score:.1f}/100) supports tradable setup with calibrated sizing.")
        elif 45 <= score < 55:
            cons.append(f"Borderline OSSE Score ({score:.1f}/100) provides insufficient statistical edge (Wait for confirmation).")
        else:
            cons.append(f"Low OSSE Score ({score:.1f}/100) indicates high risk of false breakouts & whipsaws.")

        # Safe float extraction helper for test mock compatibility
        def _safe_float(val, default=0.0):
            try:
                return float(val)
            except Exception:
                return default

        # 2. Strategy-Aware IV Rank Evaluation
        raw_iv = daily_context.get('iv_rank') if isinstance(daily_context, dict) else None
        if raw_iv is None and isinstance(raw_features, dict):
            raw_iv = raw_features.get('iv_rank')
        iv_rank_val = _safe_float(raw_iv, 50.0)

        if is_selling_strategy:
            if iv_rank_val >= 50:
                pros.append(f"High IV Rank ({iv_rank_val:.1f}%) offers rich option premiums for option selling.")
            elif iv_rank_val < 20:
                cons.append(f"Very Low IV Rank ({iv_rank_val:.1f}%) reduces option selling premium buffer.")
        elif is_buying_strategy:
            if iv_rank_val < 35:
                pros.append(f"Low IV Rank ({iv_rank_val:.1f}%) keeps option premiums cheap for directional debit strategies.")
            elif iv_rank_val >= 60:
                cons.append(f"High IV Rank ({iv_rank_val:.1f}%) increases option buying cost (elevated volatility crush risk).")
        else:
            if iv_rank_val >= 60:
                pros.append(f"Elevated IV Rank ({iv_rank_val:.1f}%) offers rich option volatility context.")
            elif iv_rank_val < 15:
                cons.append(f"Extremely Low IV Rank ({iv_rank_val:.1f}%) indicates depressed volatility environment.")

        # 3. Higher Timeframe Alignment
        htf = _safe_float(raw_features.get('htf_alignment') if isinstance(raw_features, dict) else 0, 0.0)
        if htf == 1.0:
            pros.append("15m Intraday Trend is fully aligned with Higher Timeframe Daily 20 EMA.")
        else:
            cons.append("Intraday breakout direction conflicts with Daily EMA trend (counter-trend risk).")

        # 4. Strategy-Aware ADX Trend Strength Evaluation
        adx_val = _safe_float(raw_features.get('adx') if isinstance(raw_features, dict) else 0, 0.0)
        if is_range_strategy:
            if adx_val < 20:
                pros.append(f"Low ADX ({adx_val:.1f} < 20) confirms non-trending environment ideal for range strategies.")
            elif adx_val >= 25:
                cons.append(f"High ADX ({adx_val:.1f} >= 25) signals trending momentum (Risk to range-bound short strikes).")
        else:
            if adx_val >= 25:
                pros.append(f"Strong trend momentum (ADX {adx_val:.1f} >= 25).")
            elif adx_val < 20:
                cons.append(f"Weak trend strength (ADX {adx_val:.1f} < 20), indicating choppy / ranging environment.")

        # 5. Strategy-Aware CPR Width Context Evaluation
        cpr_w_val = _safe_float(daily_context.get('cpr_width') if isinstance(daily_context, dict) else 0, 0.0)
        if cpr_w_val > 0:
            if is_range_strategy:
                if cpr_w_val > 0.6:
                    pros.append(f"Wide CPR ({cpr_w_val:.3f}%) supports range stability for non-directional selling.")
                elif cpr_w_val < 0.3:
                    cons.append(f"Narrow CPR ({cpr_w_val:.3f}%) indicates expansion risk (Breakout potential against range).")
            else:
                if cpr_w_val < 0.3:
                    pros.append(f"Narrow CPR ({cpr_w_val:.3f}%) indicates high potential for directional expansion.")
                elif cpr_w_val > 0.6:
                    cons.append(f"Wide CPR ({cpr_w_val:.3f}%) indicates a potential sideways / consolidation day.")

        # 6. VWAP Overextension Check
        vwap_dist = _safe_float(raw_features.get('vwap_distance') if isinstance(raw_features, dict) else 0, 0.0)
        if vwap_dist > 0.4:
            cons.append(f"Price is overextended ({vwap_dist:.2f}% from VWAP), increasing pull-back risk.")

        return pros, cons

    @staticmethod
    def get_error_decision(reason: str) -> dict:
        """
        Returns a rejection decision based on missing data or invalid conditions.
        """
        return {"confidence": "Reject", "decision": "NO TRADE", "reason": reason, "recommended_strategy": "No Trade"}


