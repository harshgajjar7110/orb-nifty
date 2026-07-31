import pytest
from osse.analysis.ai_chart_explainer import AIChartExplainer

def test_ai_chart_explainer():
    feature_breakdown = {
        "orb_high": 24520.0,
        "orb_low": 24450.0,
        "orb_width": 70.0,
        "cpr_pivot": 24480.0,
        "vwap": 24490.0,
        "vix": 15.2,
        "iv_rank": 65.0
    }
    strategy_recommendation = {
        "market_regime": "BULLISH_EXPANSION",
        "recommended_action": "BULL_CALL_SPREAD",
        "strategy_type": "CREDIT_SPREAD",
        "confidence_percent": 82.5,
        "rationale": "Strong breakout above 15m ORB High with CPR and VWAP alignment."
    }
    
    explanation = AIChartExplainer.explain_market_setup(
        symbol="NIFTY",
        spot_price=24535.0,
        osse_score=85.0,
        feature_breakdown=feature_breakdown,
        strategy_recommendation=strategy_recommendation
    )
    
    assert "AI Market Setup & Chart Explanation for NIFTY" in explanation
    assert "24,535.00" in explanation
    assert "85.0 / 100" in explanation
    assert "BULL_CALL_SPREAD" in explanation
