import logging
import math

logger = logging.getLogger(__name__)

class FeatureNormalizer:
    """
    Normalizes raw features to a common scale (0.0 to 1.0) based on configuration (FR-008).
    Note: In a true production system, these normalizations (like z-score or percentile)
    would be compared against a historical distribution database. For this MVP, we 
    simulate bounding logic for 0 to 1 output.
    """

    @staticmethod
    def normalize(feature_value: float, method: str, rules: dict = None, hist_stats: dict = None) -> float:
        """
        Normalizes a single feature value based on the given method.
        Returns a float between 0.0 and 1.0.
        """
        if rules is None:
            rules = {}
            
        try:
            if method == 'bounded':
                return FeatureNormalizer._bounded_scale(feature_value, rules.get('min_val', 0.0), rules.get('max_val', 1.0))
            elif method == 'min_max':
                return max(0.0, min(1.0, feature_value))
            elif method == 'rolling_z':
                if not hist_stats or 'mean_val' not in hist_stats or 'std_val' not in hist_stats:
                    logger.warning("rolling_z requested but no historical stats provided. Defaulting to 0.5")
                    return 0.5
                mean = hist_stats['mean_val']
                std = hist_stats['std_val']
                if std == 0:
                    return 0.5
                z = (feature_value - mean) / std
                # Map Z-score from [-3, 3] to [0, 1]
                return FeatureNormalizer._bounded_scale(z, -3.0, 3.0)
            elif method == 'historical_percentile':
                if not hist_stats or 'percentile_25' not in hist_stats or 'percentile_50' not in hist_stats or 'percentile_75' not in hist_stats:
                    logger.warning("historical_percentile requested but no historical stats provided. Defaulting to 0.5")
                    return 0.5
                p25 = hist_stats['percentile_25']
                p50 = hist_stats['percentile_50']
                p75 = hist_stats['percentile_75']
                
                if feature_value <= p25:
                    # Linear from 0 to 0.25
                    if p25 == 0: return 0.0
                    return 0.25 * (feature_value / p25)
                elif feature_value <= p50:
                    # Linear from 0.25 to 0.50
                    if p50 == p25: return 0.25
                    return 0.25 + 0.25 * ((feature_value - p25) / (p50 - p25))
                elif feature_value <= p75:
                    # Linear from 0.50 to 0.75
                    if p75 == p50: return 0.50
                    return 0.50 + 0.25 * ((feature_value - p50) / (p75 - p50))
                else:
                    # Linear from 0.75 to 1.0 (Assume max is around p75 * 1.5)
                    assumed_max = p75 * 1.5
                    if assumed_max <= p75: return 1.0
                    return min(1.0, 0.75 + 0.25 * ((feature_value - p75) / (assumed_max - p75)))
            else:
                logger.warning(f"Unknown normalization method {method}, returning default 0.5")
                return 0.5
        except Exception as e:
            logger.error(f"Error normalizing feature value {feature_value} with method {method}: {str(e)}")
            return 0.0

    @staticmethod
    def _bounded_scale(value: float, min_val: float, max_val: float) -> float:
        """
        Scales the value linearly between 0.0 and 1.0 based on expected min and max bounds.
        Supports inverse scaling when min_val > max_val (e.g. Narrow CPR -> higher score).
        """
        if min_val == max_val:
            return 0.5
            
        if min_val < max_val:
            # Standard scaling: smaller -> 0.0, larger -> 1.0
            scaled = (value - min_val) / (max_val - min_val)
        else:
            # Inverse scaling: smaller value -> 1.0 (Full Score), larger value -> 0.0
            scaled = (min_val - value) / (min_val - max_val)

        return max(0.0, min(1.0, scaled))

