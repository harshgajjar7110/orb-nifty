"""
AI Chart & Market Reasoning Explainer Module for OSSE.
Synthesizes quantitative metrics, DOM/screenshot inputs from Chrome MCP,
and statistical scores into natural language AI chart explanations.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AIChartExplainer:
    """
    AI Reasoning Engine that generates natural language market & chart analyses
    from fetched DOM metrics, technical indicators, and OSSE strength scores.
    """

    @staticmethod
    def explain_market_setup(
        symbol: str,
        spot_price: float,
        osse_score: float,
        feature_breakdown: Dict[str, Any],
        strategy_recommendation: Dict[str, Any],
        chart_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generates a detailed AI multi-factor chart breakdown explaining:
        1. Price & ORB Structure
        2. Technical Indicator Confluence (CPR, VWAP, EMA)
        3. Volatility & Options Strategy Recommendation
        """
        orb_high = feature_breakdown.get("orb_high", "N/A")
        orb_low = feature_breakdown.get("orb_low", "N/A")
        orb_width = feature_breakdown.get("orb_width", "N/A")
        cpr_pivot = feature_breakdown.get("cpr_pivot", "N/A")
        vwap = feature_breakdown.get("vwap", "N/A")
        vix = feature_breakdown.get("vix", 15.0)
        iv_rank = feature_breakdown.get("iv_rank", 50.0)

        # Resilient key resolution for strategy_recommendation
        regime = strategy_recommendation.get("market_regime") or strategy_recommendation.get("regime") or "BALANCED"
        action = strategy_recommendation.get("recommended_action") or strategy_recommendation.get("recommended_strategy") or strategy_recommendation.get("decision") or "NO TRADE"
        strategy_type = strategy_recommendation.get("strategy_type") or strategy_recommendation.get("decision") or "NEUTRAL"
        
        raw_conf = strategy_recommendation.get("confidence_percent") or strategy_recommendation.get("confidence") or 50.0
        confidence_str = f"{raw_conf:.1f}%" if isinstance(raw_conf, (int, float)) else str(raw_conf)
        
        rationale = strategy_recommendation.get("rationale") or strategy_recommendation.get("reason") or "Statistical edge evaluation complete."

        # Breakout status check
        breakout_status = "WITHIN"
        if isinstance(orb_high, (int, float)) and spot_price > orb_high:
            breakout_status = "ABOVE"
        elif isinstance(orb_low, (int, float)) and spot_price < orb_low:
            breakout_status = "BELOW"

        # VWAP status check
        vwap_status = "Neutral"
        if isinstance(vwap, (int, float)):
            vwap_status = "Bullish (Above VWAP)" if spot_price >= vwap else "Bearish (Below VWAP)"

        explanation = f"""### 🤖 AI Market Setup & Chart Explanation for {symbol}

#### 1. Price Action & 15-Minute ORB Structure
- **Current Spot Price**: `₹{spot_price:,.2f}`
- **Opening Range (09:15-09:30 AM)**: High `₹{orb_high}` | Low `₹{orb_low}` | Range Width `{orb_width} pts`
- **Breakout Status**: Price is currently trading **{breakout_status}** the 15-minute Opening Range.

#### 2. Key Indicator Confluence
- **Central Pivot Range (CPR)**: Pivot level at `₹{cpr_pivot}`.
- **Volume Weighted Average Price (VWAP)**: Currently at `₹{vwap}` ({vwap_status}).
- **Volatility Environment**: India VIX at `{vix}` (IV Rank: `{iv_rank}%`).

#### 3. Quantitative OSSE Score & AI Recommendation
- **Statistical Strength Score**: `{osse_score:.1f} / 100` (Confidence: `{confidence_str}`)
- **Detected Market Regime**: `{regime}`
- **Recommended Strategy**: **{action}** ({strategy_type})
- **AI Rationale**: {rationale}

---
*Generated autonomously via OSSE AI Engine + Data Pipeline.*
"""
        return explanation
