import sys
from unittest.mock import MagicMock

# Mock talib before any imports
sys.modules['talib'] = MagicMock()

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from osse.api.app import app

client = TestClient(app)

def test_generate_score_success():
    with patch('osse.api.app.DataCollector.fetch_data') as mock_fetch_data, \
         patch('osse.api.app.DataCollector.fetch_daily_context') as mock_fetch_daily, \
         patch('osse.api.app.DataValidator.validate_intraday_data') as mock_val_intra, \
         patch('osse.api.app.DataValidator.validate_daily_context') as mock_val_daily, \
         patch('osse.api.app.IndicatorEngine.add_indicators') as mock_ind, \
         patch('osse.api.app.ORBBuilder.calculate_orb_stats') as mock_orb, \
         patch('osse.api.app.FeatureEngineering.extract_features') as mock_feat, \
         patch('osse.api.app.ScoringEngine.calculate_score') as mock_score, \
         patch('osse.api.app.DecisionEngine.get_decision') as mock_decision:
        
        mock_val_intra.return_value = True
        mock_val_daily.return_value = True
        mock_orb.return_value = {'orb_width': 10}
        mock_feat.return_value = {'adx': 25}
        mock_score.return_value = 85.0
        mock_decision.return_value = {'confidence': 'High', 'decision': 'TRADE'}

        response = client.post("/api/v1/score", json={"symbol": "^NSEI", "date": "2023-01-01"})
        
        assert response.status_code == 200
        data = response.json()
        assert data['score'] == 85.0
        assert data['confidence'] == 'High'
        assert data['decision'] == 'TRADE'
        assert data['regime'] == 'TREND'

def test_generate_score_invalid_data():
    with patch('osse.api.app.DataCollector.fetch_data'), \
         patch('osse.api.app.DataCollector.fetch_daily_context'), \
         patch('osse.api.app.DataValidator.validate_intraday_data', return_value=False):
        
        response = client.post("/api/v1/score", json={"symbol": "^NSEI", "date": "2023-01-01"})
        
        assert response.status_code == 200
        data = response.json()
        assert data['score'] == 0.0
        assert data['decision'] == 'NO TRADE'
        assert data['confidence'] == 'Reject'

