"""
DOM Parser Module for OSSE.
Cleans raw DOM scraping results into structured DataFrames.
"""
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class DOMParser:
    """
    Parses and sanitizes raw JSON/DOM payloads returned by Chrome MCP.
    """

    @staticmethod
    def parse_nse_option_chain(dom_payload: Dict[str, Any]) -> Tuple[Optional[float], pd.DataFrame]:
        """
        Parses NSE Option Chain DOM payload into spot price and option chain DataFrame.
        """
        if not dom_payload or not isinstance(dom_payload, dict):
            logger.warning("Empty or invalid DOM payload passed to parse_nse_option_chain.")
            return None, pd.DataFrame()

        spot_price = dom_payload.get('spot_price')
        raw_chain = dom_payload.get('option_chain', [])

        if not raw_chain:
            logger.warning("No option chain rows found in DOM payload.")
            return spot_price, pd.DataFrame()

        df = pd.DataFrame(raw_chain)
        required_cols = ['strike', 'call_ltp', 'call_iv', 'call_oi', 'put_ltp', 'put_iv', 'put_oi']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0.0

        # Data sanitization
        df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0.0)
        df['call_ltp'] = pd.to_numeric(df['call_ltp'], errors='coerce').fillna(0.0)
        df['call_iv'] = pd.to_numeric(df['call_iv'], errors='coerce').fillna(0.0)
        df['call_oi'] = pd.to_numeric(df['call_oi'], errors='coerce').fillna(0.0)
        df['put_ltp'] = pd.to_numeric(df['put_ltp'], errors='coerce').fillna(0.0)
        df['put_iv'] = pd.to_numeric(df['put_iv'], errors='coerce').fillna(0.0)
        df['put_oi'] = pd.to_numeric(df['put_oi'], errors='coerce').fillna(0.0)

        df = df[df['strike'] > 0].sort_values('strike').reset_index(drop=True)
        return spot_price, df

    @staticmethod
    def parse_generic_table(table_payload: Dict[str, Any]) -> pd.DataFrame:
        """
        Converts generic scraped HTML table headers & rows into a DataFrame.
        """
        if not table_payload or 'rows' not in table_payload:
            return pd.DataFrame()

        headers = table_payload.get('headers', [])
        rows = table_payload.get('rows', [])

        if not rows:
            return pd.DataFrame()

        if headers and len(headers) == len(rows[0]):
            df = pd.DataFrame(rows, columns=headers)
        else:
            df = pd.DataFrame(rows)

        return df
