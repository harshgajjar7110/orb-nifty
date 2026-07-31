import pytest
from osse.engine.confluence import ConfluenceEngine


def test_confluence_score_perfect_alignment():
    engine = ConfluenceEngine(step_size=50.0)

    dex_data = {
        "call_wall": 24600.0,
        "put_support": 24400.0,
        "delta_flip": 24500.0,
        "dex_clusters": [24600.0, 24400.0]
    }
    vp_data = {
        "poc": 24500.0,
        "vah": 24600.0,
        "val": 24400.0,
        "volume_delta": 50000.0
    }
    spot = 24500.0

    res = engine.calculate_confluence_score(dex_data, vp_data, spot_price=spot, avg_volume_delta=30000.0)

    assert res["status"] == "SUCCESS"
    assert res["confluence_score"] >= 80.0
    assert res["tier"] == "Tier 1 (Strong)"
    assert len(res["alignment_rules"]) >= 2


def test_unified_score():
    engine = ConfluenceEngine()
    res = engine.calculate_unified_score(osse_score=80.0, confluence_score=90.0)
    
    # Unified = 0.4 * 80 + 0.6 * 90 = 32 + 54 = 86
    assert res["unified_score"] == 86.0
    assert res["tier"] == "Tier 1"
