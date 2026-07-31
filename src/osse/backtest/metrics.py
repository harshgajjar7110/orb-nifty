import pandas as pd
from typing import List, Dict

class MetricsCalculator:
    """
    Calculates basic performance metrics on OSSE scoring decisions.
    """

    @staticmethod
    def calculate_summary(results: List[Dict]) -> Dict:
        """
        Takes a list of daily result dicts and returns a summary.
        """
        if not results:
            return {"error": "No results provided"}
            
        df = pd.DataFrame(results)
        
        total_days = len(df)
        trades_passed = len(df[df['decision'].isin(['TRADE', 'REDUCED SIZE'])])
        reduced_size = len(df[df['decision'] == 'REDUCED SIZE'])
        trades_rejected = len(df[~df['decision'].isin(['TRADE', 'REDUCED SIZE'])])
        
        avg_score = df['score'].mean()
        max_score = df['score'].max()
        min_score = df['score'].min()
        
        pnl_series = df['trade_pnl'].dropna() if 'trade_pnl' in df.columns else pd.Series()
        wins = len(pnl_series[pnl_series > 0])
        win_rate = (wins / len(pnl_series) * 100) if len(pnl_series) > 0 else 0.0

        avg_mfe = df['mfe'].mean() if 'mfe' in df.columns and not df['mfe'].dropna().empty else 0.0
        avg_mae = df['mae'].mean() if 'mae' in df.columns and not df['mae'].dropna().empty else 0.0
        mfe_mae_ratio = (avg_mfe / avg_mae) if avg_mae > 0 else 0.0

        return {
            "total_days_evaluated": total_days,
            "trades_approved": trades_passed,
            "trades_reduced": reduced_size,
            "trades_rejected": trades_rejected,
            "approval_rate": round((trades_passed / total_days) * 100, 2) if total_days > 0 else 0,
            "win_rate": round(win_rate, 2),
            "average_score": round(avg_score, 2),
            "max_score": round(max_score, 2),
            "min_score": round(min_score, 2),
            "avg_mfe": round(avg_mfe, 2),
            "avg_mae": round(avg_mae, 2),
            "mfe_mae_ratio": round(mfe_mae_ratio, 2)
        }
