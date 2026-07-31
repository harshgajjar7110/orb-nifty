import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import pytest

from osse.agent.exposure_agent import DhanExposureAgent


@pytest.fixture
def delta_snapshot():
    path = "/tmp/dhan_dashboard_snapshot.json"
    if not os.path.exists(path):
        pytest.skip("Saved Delta snapshot not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def gamma_snapshot():
    path = "/tmp/dhan_gamma_snapshot.json"
    if not os.path.exists(path):
        pytest.skip("Saved Gamma snapshot not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_exposure_agent_webbridge_path(delta_snapshot, gamma_snapshot):
    from osse.data.webbridge_collector import WebBridgeCollector

    agent = DhanExposureAgent(daemon_url="http://127.0.0.1:1", use_mcp_fallback=False)

    # Use a real WebBridgeCollector for text flattening, but mock the daemon
    # interaction methods so the test runs offline.
    real_collector = WebBridgeCollector(daemon_url="")
    mock_collector = MagicMock(wraps=real_collector)
    mock_collector.ensure_daemon.return_value = True
    mock_collector.navigate.return_value = {"success": True}
    mock_collector.find_tab_and_click.return_value = True

    def snapshot_side_effect():
        snapshot_side_effect.calls = getattr(snapshot_side_effect, "calls", 0)
        snapshot_side_effect.calls += 1
        return delta_snapshot if snapshot_side_effect.calls == 1 else gamma_snapshot

    mock_collector.snapshot.side_effect = snapshot_side_effect

    with patch.object(agent, "webbridge", mock_collector):
        result = agent.run(
            url="https://dext.dhan.co/dashboard",
            symbol="NIFTY",
            direction="UP",
            strategy_name="Directional Credit Spread",
        )

    assert result.status == "SUCCESS"
    assert result.collector_used == "webbridge"
    assert result.delta_exposure is not None
    assert result.gamma_exposure is not None
    assert result.spot_price is not None
    assert result.strike_recommendation.get("variant_used") == "GEX_DEX_ALIGNED"
    assert len(result.strike_recommendation.get("legs", [])) == 2


def test_exposure_agent_mcp_fallback():
    agent = DhanExposureAgent(daemon_url="http://127.0.0.1:1", use_mcp_fallback=True)
    result = agent.run(
        url="https://dext.dhan.co/dashboard",
        symbol="NIFTY",
        direction="DOWN",
        strategy_name="Directional Credit Spread",
    )
    # Without WebBridge daemon, it should fall back to MCP/synthetic.
    assert result.status == "SUCCESS"
    assert result.collector_used == "dhan_mcp"
    assert result.strike_recommendation.get("variant_used") == "GEX_DEX_ALIGNED"
    legs = result.strike_recommendation.get("legs", [])
    assert len(legs) == 2
    assert legs[0]["option_type"] == "CE"
    assert legs[0]["strike"] > result.spot_price
