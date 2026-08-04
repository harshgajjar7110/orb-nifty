import pandas as pd
from typing import List, Dict

class MetricsCalculator:
    """
    Calculates performance metrics on OSSE scoring decisions.
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

    @staticmethod
    def calculate_regime_stratified(results: List[Dict]) -> Dict:
        """
        Returns MFE/MAE and win-rate metrics stratified by market regime.
        """
        if not results:
            return {"error": "No results provided"}

        df = pd.DataFrame(results)
        if 'market_regime' not in df.columns:
            return MetricsCalculator.calculate_summary(results)

        regimes = df['market_regime'].dropna().unique()
        regime_metrics = {}

        for regime in regimes:
            regime_df = df[df['market_regime'] == regime]
            regime_pnl = regime_df['trade_pnl'].dropna() if 'trade_pnl' in regime_df.columns else pd.Series()
            regime_wins = len(regime_pnl[regime_pnl > 0]) if len(regime_pnl) > 0 else 0
            regime_mfe = regime_df['mfe'].mean() if 'mfe' in regime_df.columns and not regime_df['mfe'].dropna().empty else 0.0
            regime_mae = regime_df['mae'].mean() if 'mae' in regime_df.columns and not regime_df['mae'].dropna().empty else 0.0
            regime_mfe_mae = (regime_mfe / regime_mae) if regime_mae > 0 else 0.0

            regime_metrics[regime] = {
                "days": len(regime_df),
                "trades": len(regime_df[regime_df['decision'].isin(['TRADE', 'REDUCED SIZE'])]),
                "wins": regime_wins,
                "win_rate": round((regime_wins / len(regime_pnl) * 100), 2) if len(regime_pnl) > 0 else 0.0,
                "avg_mfe": round(regime_mfe, 2),
                "avg_mae": round(regime_mae, 2),
                "mfe_mae_ratio": round(regime_mfe_mae, 2),
                "avg_pnl": round(regime_pnl.mean(), 2) if len(regime_pnl) > 0 else 0.0
            }

        return {
            "by_regime": regime_metrics,
            "regimes_evaluated": len(regimes)
        }
