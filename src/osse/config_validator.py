# src/osse/config_validator.py
import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

# Define Pydantic-like schema validation manually for scoring_rules.yaml
REQUIRED_SECTIONS = [
    'features',
    'confluence_weights',
    'unified_score_weights',
    'regimes'
]

REQUIRED_FEATURE_KEYS = [
    'weight', 'normalization', 'min_val', 'max_val'
]

def validate_scorer_config(config: dict) -> List[str]:
    """Validate the scorer configuration and return a list of validation errors."""
    errors = []
    
    # Check required top-level sections
    for section in REQUIRED_SECTIONS:
        if section not in config:
            errors.append(f"Missing required section '{section}'")
    
    # Validate features
    if 'features' in config:
        for feature_name, feature_config in config['features'].items():
            if not isinstance(feature_config, dict):
                errors.append(f"Features section: '{feature_name}' must be a mapping")
                continue
            
            # Check required keys for each feature
            missing_keys = [key for key in REQUIRED_FEATURE_KEYS if key not in feature_config]
            if missing_keys:
                errors.append(f"Features section: '{feature_name}' missing required keys: {', '.join(missing_keys)}")
            
            # Validate normalization method
            norm_method = feature_config.get('normalization', '')
            if norm_method not in ['bounded', 'min_max', 'rolling_z', 'historical_percentile']:
                errors.append(f"Features section: '{feature_name}' has invalid normalization method '{norm_method}'")
            
            # If min_val and max_val are present, validate numeric type
            if not isinstance(feature_config.get('min_val'), (int, float)):
                errors.append(f"Features section: '{feature_name}' min_val must be numeric")
            if not isinstance(feature_config.get('max_val'), (int, float)):
                errors.append(f"Features section: '{feature_name}' max_val must be numeric")
    
    # Validate unified_score_weights
    if 'unified_score_weights' in config:
        weights = config['unified_score_weights']
        osse_weight = weights.get('osse_score_weight')
        confluence_weight = weights.get('confluence_score_weight')
        if osse_weight is None or confluence_weight is None:
            errors.append("unified_score_weights missing required keys: 'osse_score_weight', 'confluence_score_weight'")
        elif not isinstance(osse_weight, (int, float)) or not isinstance(confluence_weight, (int, float)):
            errors.append("unified_score_weights weights must be numeric")
        elif osse_weight < 0 or confluence_weight < 0:
            errors.append("unified_score_weights weights must be non-negative")
        elif abs(osse_weight + confluence_weight - 1.0) > 0.01:  # Allow small floating point errors
            errors.append(f"unified_score_weights must sum to 1.0, got osse={osse_weight}, confluence={confluence_weight}")
    
    # Validate regimes
    if 'regimes' in config and not isinstance(config['regimes'], dict):
        errors.append("regimes must be a mapping")
    
    # Validate confluence_weights
    if 'confluence_weights' in config:
        weights = config['confluence_weights']
        required_confluence_keys = ['dex_wall_at_vp_boundary', 'poc_near_dex_flip', 'vah_val_near_dex', 'volume_confirmation']
        missing = [key for key in required_confluence_keys if key not in weights]
        if missing:
            errors.append(f"confluence_weights missing required keys: {', '.join(missing)}")
        for key, val in weights.items():
            if not isinstance(val, (int, float)):
                errors.append(f"confluence_weights values must be integers, found {type(val).__name__} for key '{key}'")
    
    return errors

def load_and_validate_config(config_path: str) -> tuple[dict, List[str]]:
    """Load config file and validate it."""
    if not Path(config_path).exists():
        return {}, [f"Config file '{config_path}' does not exist"]
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return {}, [f"YAML parse error in '{config_path}': {str(e)}"]
    
    errors = validate_scorer_config(config)
    return config, errors

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_config.py <config_path>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    config, errors = load_and_validate_config(config_path)
    
    if errors:
        print("Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print("Configuration validation passed!")
        sys.exit(0)