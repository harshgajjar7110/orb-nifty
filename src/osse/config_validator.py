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
    'regimes'
]

REQUIRED_FEATURE_KEYS = [
    'weight', 'normalization', 'min_val', 'max_val'
]

VALID_NORMALIZATION_METHODS = ['bounded', 'min_max', 'rolling_z', 'historical_percentile']

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
            if norm_method not in VALID_NORMALIZATION_METHODS:
                errors.append(f"Features section: '{feature_name}' has invalid normalization method '{norm_method}'")
            
            # If min_val and max_val are present, validate numeric type
            if not isinstance(feature_config.get('min_val'), (int, float)):
                errors.append(f"Features section: '{feature_name}' min_val must be numeric")
            if not isinstance(feature_config.get('max_val'), (int, float)):
                errors.append(f"Features section: '{feature_name}' max_val must be numeric")
    
    # Validate regimes
    if 'regimes' in config and not isinstance(config['regimes'], dict):
        errors.append("regimes must be a mapping")
    
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
