import yaml
import logging
from typing import Dict, Any
from .normalizer import FeatureNormalizer
import os

logger = logging.getLogger(__name__)

class ScoringEngine:
    """
    Computes the final ORB Strength Score (FR-009).
    Loads configuration from config/scoring_rules.yaml.
    """

    def __init__(self, config_path: str = None):
        if not config_path:
            # Default path relative to this file
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            config_path = os.path.join(base_dir, 'config', 'scoring_rules.yaml')
            
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                self.features_config = self.config.get('features', {})
        except Exception as e:
            logger.error(f"Failed to load scoring config from {config_path}: {e}")
            self.features_config = {}

    def calculate_score_detailed(self, raw_features: Dict[str, float], historical_stats: Dict[str, dict] = None, regime: str = "NEUTRAL") -> tuple[float, list]:
        """
        Returns (final_score, breakdown)
        """
        if historical_stats is None:
            historical_stats = {}
            
        total_score = 0.0
        total_weight = 0.0
        breakdown = []
        
        regime_overrides = self.config.get('regimes', {}).get(regime, {})

        for feature_name, feature_val in raw_features.items():
            if feature_name in self.features_config:
                # Merge base rules with any regime overrides
                rules = self.features_config[feature_name].copy()
                if feature_name in regime_overrides:
                    rules.update(regime_overrides[feature_name])
                    
                weight = rules.get('weight', 0)
                norm_method = rules.get('normalization', 'bounded')
                
                feat_hist_stats = historical_stats.get(feature_name, {})
                normalized_val = FeatureNormalizer.normalize(feature_val, norm_method, rules, feat_hist_stats)
                contribution = weight * normalized_val
                
                total_score += contribution
                total_weight += weight
                
                breakdown.append({
                    "Feature": feature_name,
                    "Raw Value": round(feature_val, 4),
                    "Normalized Value": round(normalized_val, 4),
                    "Weight": weight,
                    "Score Contribution": round(contribution, 4)
                })
                
        # If total_weight doesn't add up to 100, scale it proportionately to 100 max score
        if total_weight > 0:
            final_score = (total_score / total_weight) * 100.0
        else:
            final_score = 0.0
            
        # Add relative contribution to the final scaled score
        for item in breakdown:
            if total_weight > 0:
                scaled_contribution = (item["Score Contribution"] / total_weight) * 100.0
                item["Scaled Contribution"] = round(scaled_contribution, 2)
            else:
                item["Scaled Contribution"] = 0.0
                
        logger.info(f"Score engine calculated final score: {final_score:.2f} / 100")
            
        return round(final_score, 2), breakdown

    def calculate_score(self, raw_features: Dict[str, float], historical_stats: Dict[str, dict] = None, regime: str = "NEUTRAL") -> float:
        """
        Score = Sum(Weight * NormalizedFeature)
        """
        final_score, _ = self.calculate_score_detailed(raw_features, historical_stats, regime)
        return final_score

