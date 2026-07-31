import pytest
from osse.engine.strategy_variants import StrategyVariantSelector


def test_strategy_variant_selection():
    selector = StrategyVariantSelector(symbol="NIFTY", step_size=50.0)

    confluence_data = {"confluence_score": 85.0}
    dex_data = {
        "status": "SUCCESS",
        "call_wall": 24700.0,
        "put_support": 24300.0,
        "delta_flip": 24500.0,
        "dex_clusters": [24700.0]
    }
    vp_data = {
        "status": "SUCCESS",
        "poc": 24500.0,
        "vah": 24700.0,
        "val": 24300.0,
        "lvn_array": [24600.0]
    }

    variants = selector.select_variants(
        spot_price=24500.0,
        confluence_data=confluence_data,
        dex_data=dex_data,
        vp_data=vp_data,
        vix=16.0,
        pcr_oi=1.0
    )

    assert len(variants) > 0
    variant_names = [v["variant_name"] for v in variants]
    assert any("Strangle" in name or "Condor" in name or "Ratio" in name for name in variant_names)
