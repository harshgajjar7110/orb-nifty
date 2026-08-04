import pytest
import os
import pandas as pd
import numpy as np
from unittest.mock import patch
from osse.data.db import DatabaseManager, _sanitize

def test_database_manager_paths():
    DatabaseManager._initialize_paths()
    assert DatabaseManager._data_dir is not None
    assert os.path.exists(DatabaseManager._data_dir)

def test_sanitize_helper():
    assert _sanitize(42.0) == 42.0
    assert _sanitize(None) == 0.0
    assert _sanitize(float('nan')) == 0.0
    assert _sanitize(float('inf')) == 0.0
    assert _sanitize("not_a_number") == 0.0
    assert _sanitize(0) == 0.0
    assert _sanitize("3.14") == 3.14

def test_save_analysis_parquet(tmp_path):
    score_file = os.path.join(tmp_path, "orb_strength_score.parquet")
    with patch.object(DatabaseManager, '_score_file', str(score_file)):
        with patch.object(DatabaseManager, '_data_dir', str(tmp_path)):
            DatabaseManager.save_analysis("2026-07-20", "^NSEI", {"adx": 25.0}, {"orb_high": 24000, "orb_low": 23900}, 85.0, {"decision": "TRADE"})
            assert os.path.exists(score_file)
            df = pd.read_parquet(score_file)
            assert not df.empty
            assert df['symbol'].iloc[0] == "^NSEI"
            assert df['normalized_score'].iloc[0] == 85.0

def test_save_analysis_with_calibrated_score(tmp_path):
    score_file = os.path.join(tmp_path, "orb_strength_score.parquet")
    with patch.object(DatabaseManager, '_score_file', str(score_file)):
        with patch.object(DatabaseManager, '_data_dir', str(tmp_path)):
            DatabaseManager.save_analysis(
                "2026-07-20", "^NSEI", {"adx": 25.0}, {"orb_high": 24000, "orb_low": 23900},
                85.0, {"decision": "TRADE"},
                calibrated_score=82.5, confluence_score=78.0, unified_score=80.2, ml_probability=0.73
            )
            assert os.path.exists(score_file)
            df = pd.read_parquet(score_file)
            assert not df.empty
            assert df['calibrated_score'].iloc[0] == 82.5
            assert df['confluence_score'].iloc[0] == 78.0
            assert df['unified_score'].iloc[0] == 80.2
            assert df['ml_probability'].iloc[0] == 0.73

def test_save_analysis_nan_handling(tmp_path):
    score_file = os.path.join(tmp_path, "orb_strength_score.parquet")
    with patch.object(DatabaseManager, '_score_file', str(score_file)):
        with patch.object(DatabaseManager, '_data_dir', str(tmp_path)):
            DatabaseManager.save_analysis(
                "2026-07-20", "^NSEI",
                {"adx": np.nan, "vwap_distance": np.nan, "relative_volume": 0.0},
                {"orb_high": 24000, "orb_low": 23900}, 85.0, {"decision": "TRADE"}
            )
            assert os.path.exists(score_file)
            df = pd.read_parquet(score_file)
            assert not df.empty
            assert df['adx'].iloc[0] == 0.0
            assert df['vwap_distance'].iloc[0] == 0.0
            assert df['relative_volume'].iloc[0] == 0.0

def test_get_historical_stats(tmp_path):
    dist_file = os.path.join(tmp_path, "feature_distributions.parquet")
    df_sample = pd.DataFrame([{
        "date": "2026-07-20",
        "symbol": "^NSEI",
        "feature_name": "adx",
        "mean_val": 25.0,
        "std_val": 5.0
    }])
    df_sample.to_parquet(dist_file)
    
    with patch.object(DatabaseManager, '_dist_file', str(dist_file)):
        stats = DatabaseManager.get_historical_stats("2026-07-20", "^NSEI")
        assert "adx" in stats
        assert stats["adx"]["mean_val"] == 25.0
