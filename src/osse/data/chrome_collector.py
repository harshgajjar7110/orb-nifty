"""
Chrome Collector Module for OSSE.
Interfaces with Chrome DevTools MCP tools for live browser navigation,
DOM data extraction, and network API response parsing.
"""
import os
import yaml
import logging
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from osse.data.dom_parser import DOMParser

logger = logging.getLogger(__name__)

class ChromeCollector:
    """
    Chrome DevTools MCP Web Scraping Engine for OSSE.
    Executes live browser queries and extracts DOM nodes / network responses.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "config", "chrome_targets.yaml"
            )
        
        self.config_path = config_path
        self.targets = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Loads Chrome target definitions from YAML config."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Chrome targets config not found at {self.config_path}")
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("targets", {})
        except Exception as e:
            logger.error(f"Failed to load chrome_targets.yaml: {str(e)}")
            return {}

    def get_target_config(self, target_key: str) -> Dict[str, Any]:
        """Returns configuration for a specific web scraping target."""
        return self.targets.get(target_key, {})

    def build_extraction_script(self, target_key: str) -> Optional[str]:
        """
        Retrieves the JavaScript DOM extraction snippet for a given target.
        """
        target = self.get_target_config(target_key)
        return target.get("js_extractor")

    def process_raw_dom_data(self, target_key: str, raw_payload: Dict[str, Any]) -> Tuple[Optional[float], pd.DataFrame]:
        """
        Routes raw JS payload extracted via Chrome MCP to the appropriate DOMParser method.
        """
        if target_key == "nse_option_chain":
            return DOMParser.parse_nse_option_chain(raw_payload)
        elif target_key == "tradingview_nifty":
            spot = raw_payload.get("spot_price")
            df = pd.DataFrame([raw_payload]) if spot else pd.DataFrame()
            return spot, df
        else:
            df = DOMParser.parse_generic_table(raw_payload)
            return None, df
