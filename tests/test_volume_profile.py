import pytest
import pandas as pd
import numpy as np
from osse.features.volume_profile import VolumeProfileCalculator


def test_volume_profile_basic():
    calc = VolumeProfileCalculator(va_percent=0.70, num_bins=20)
    
    # Generate mock candles
    candles = []
    prices = np.linspace(24400, 24600, 30)
    for p in prices:
        candles.append({
            "high": p + 10,
            "low": p - 10,
            "open": p - 5,
            "close": p + 5,
            "volume": 10000
        })
    df = pd.DataFrame(candles)

    res = calc.calculate_volume_profile(df)

    assert res["status"] == "SUCCESS"
    assert res["poc"] > 0
    assert res["vah"] >= res["poc"]
    assert res["val"] <= res["poc"]
    assert res["total_volume"] == 300000


def test_volume_profile_empty():
    calc = VolumeProfileCalculator()
    res = calc.calculate_volume_profile(pd.DataFrame())
    assert res["status"] == "ERROR"
