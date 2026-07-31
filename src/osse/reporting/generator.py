import pandas as pd
import logging
from typing import List, Dict
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class ReportGenerator:
    """
    Generates reports (JSON, CSV) based on backtest or live trading metrics.
    """

    @staticmethod
    def generate_json_report(metrics: Dict, filepath: str = "report.json"):
        """
        Saves a summary metrics dictionary to a JSON file.
        """
        try:
            report_data = {
                "generated_at": datetime.now().isoformat(),
                "metrics": metrics
            }
            with open(filepath, 'w') as f:
                json.dump(report_data, f, indent=4)
            logger.info(f"JSON report saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to generate JSON report: {e}")

    @staticmethod
    def generate_csv_report(results: List[Dict], filepath: str = "backtest_results.csv"):
        """
        Saves the raw backtest results to a CSV file.
        """
        try:
            if not results:
                logger.warning("No results to save.")
                return
            df = pd.DataFrame(results)
            df.to_csv(filepath, index=False)
            logger.info(f"CSV report saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to generate CSV report: {e}")
