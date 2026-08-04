"""
Confluence Engine for OSSE.

Synthesizes Delta Exposure (DEX) positioning with Volume Profile 70% Value Area
and existing OSSE statistical scores to compute Confluence Scores and Alignment Rules.
"""

import os
import yaml
from typing import Dict, List, Any, Optional
import numpy as np


class ConfluenceEngine:
    """
    Evaluates convergence between DEX walls, Volume Profile boundaries (VAH/VAL/POC),
    and ORB directional strength.
    """

    def __init__(self, step_size: float = 50.0, config_path: Optional[str] = None):
        self.step_size = step_size
        self.config = self._load_config(config_path)

    def _load_config(self, path: Optional[str]) -> dict:
        if path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            path = os.path.join(base_dir, "config", "scoring_rules.yaml")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def calculate_confluence_score(
        self,
        dex_data: Dict[str, Any],
        vp_data: Dict[str, Any],
        spot_price: float,
        avg_volume_delta: float = 0.0,
        step_size: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates Confluence Score (0-100) from DEX and VP data using config-driven weights.
        """
        if spot_price <= 0:
            return self._empty_response("Invalid spot price.")

        effective_step = step_size or self.step_size
        conf_weights = self.config.get("confluence_weights", {})

        w_wall_vp = float(conf_weights.get("dex_wall_at_vp_boundary", 40.0))
        w_poc_flip = float(conf_weights.get("poc_near_dex_flip", 30.0))
        w_cluster = float(conf_weights.get("vah_val_near_dex", 20.0))
        w_vol_confirm = float(conf_weights.get("volume_confirmation", 10.0))

        def safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        call_wall = safe_float(dex_data.get("call_wall"))
        put_support = safe_float(dex_data.get("put_support"))
        delta_flip = safe_float(dex_data.get("delta_flip"))
        dex_clusters = dex_data.get("dex_clusters", [])

        poc = safe_float(vp_data.get("poc"))
        vah = safe_float(vp_data.get("vah"))
        val = safe_float(vp_data.get("val"))
        vol_delta = safe_float(vp_data.get("volume_delta"))

        # 1. DEX wall at VP boundary
        cw_at_vah = abs(call_wall - vah) / spot_price <= 0.003 if (call_wall > 0 and vah > 0) else False
        ps_at_val = abs(put_support - val) / spot_price <= 0.003 if (put_support > 0 and val > 0) else False
        score_wall_vp = w_wall_vp if (cw_at_vah or ps_at_val) else 0.0

        # 2. POC near DEX flip
        score_poc_flip = w_poc_flip if (poc > 0 and delta_flip > 0 and abs(poc - delta_flip) / spot_price <= 0.002) else 0.0

        # 3. VAH/VAL within 1 strike of any DEX cluster
        score_near_cluster = 0.0
        if len(dex_clusters) > 0:
            for cluster in dex_clusters:
                if (vah > 0 and abs(vah - cluster) <= effective_step) or (val > 0 and abs(val - cluster) <= effective_step):
                    score_near_cluster = w_cluster
                    break

        # 4. Volume confirmation
        vol_confirm = False
        if avg_volume_delta > 0:
            vol_confirm = abs(vol_delta) > (1.2 * avg_volume_delta)
        elif abs(vol_delta) > 0:
            vol_confirm = True # Default confirmation if positive volume delta present
        score_vol_confirm = w_vol_confirm if vol_confirm else 0.0

        confluence_score = score_wall_vp + score_poc_flip + score_near_cluster + score_vol_confirm

        # Confluence Tier
        if confluence_score >= 80:
            tier = "Tier 1 (Strong)"
            action = "Primary strategy variant; full position size (2% risk)"
        elif confluence_score >= 60:
            tier = "Tier 2 (Moderate)"
            action = "Secondary variant with tighter sizing (1% risk)"
        elif confluence_score >= 40:
            tier = "Tier 3 (Weak)"
            action = "Paper trade only or avoid (0.5% risk)"
        else:
            tier = "No Trade"
            action = "Skip entirely"

        # Check Alignment Rules R1 - R6
        rules_triggered = self.evaluate_alignment_rules(
            call_wall=call_wall,
            put_support=put_support,
            delta_flip=delta_flip,
            dex_clusters=dex_clusters,
            poc=poc,
            vah=vah,
            val=val,
            lvn_array=vp_data.get("lvn_array", []),
            spot_price=spot_price
        )

        return {
            "status": "SUCCESS",
            "confluence_score": confluence_score,
            "tier": tier,
            "recommended_action": action,
            "components": {
                "dex_wall_at_vp_boundary": score_wall_vp,
                "poc_near_dex_flip": score_poc_flip,
                "vah_val_near_dex": score_near_cluster,
                "volume_confirmation": score_vol_confirm
            },
            "alignment_rules": rules_triggered
        }

    def evaluate_alignment_rules(
        self,
        call_wall: float,
        put_support: float,
        delta_flip: float,
        dex_clusters: List[float],
        poc: float,
        vah: float,
        val: float,
        lvn_array: List[float],
        spot_price: float
    ) -> List[Dict[str, Any]]:
        """
        Evaluates alignment rules R1 to R6.
        """
        rules = []

        # R1: Call Wall @ VAH
        if call_wall > 0 and vah > 0 and abs(call_wall - vah) / spot_price <= 0.003:
            rules.append({
                "rule": "R1: Call Wall @ VAH",
                "condition": "DEX Call Wall within ±0.3% of VP VAH",
                "strike_guidance": "Use VAH as call strike for strangle / call credit spread"
            })

        # R2: Put Support @ VAL
        if put_support > 0 and val > 0 and abs(put_support - val) / spot_price <= 0.003:
            rules.append({
                "rule": "R2: Put Support @ VAL",
                "condition": "DEX Put Support within ±0.3% of VP VAL",
                "strike_guidance": "Use VAL as put strike for strangle / put credit spread"
            })

        # R3: POC @ Delta Flip
        if poc > 0 and delta_flip > 0 and abs(poc - delta_flip) / spot_price <= 0.002:
            rules.append({
                "rule": "R3: POC @ Delta Flip",
                "condition": "VP POC within ±0.2% of DEX Delta Flip",
                "strike_guidance": "Session pivot; bias trades accordingly"
            })

        # R4: LVN Air Pocket
        if call_wall > 0 and len(lvn_array) > 0:
            lvn_in_between = [lvn for lvn in lvn_array if spot_price < lvn < call_wall]
            if len(lvn_in_between) > 0:
                rules.append({
                    "rule": "R4: LVN Air Pocket",
                    "condition": "LVN exists between spot/DEX levels",
                    "strike_guidance": "Credit spread target = next cluster; wide profit zone"
                })

        # R5: Tight VAH-VAL
        if vah > 0 and val > 0:
            range_pct = (vah - val) / spot_price
            if range_pct < 0.012:
                rules.append({
                    "rule": "R5: Tight VAH-VAL",
                    "condition": f"VAH-VAL range ({range_pct*100:.2f}%) < 1.2% of spot",
                    "strike_guidance": "Market balanced; favor short straddle over strangle"
                })
            elif range_pct > 0.025:
                # R6: Wide VAH-VAL
                rules.append({
                    "rule": "R6: Wide VAH-VAL",
                    "condition": f"VAH-VAL range ({range_pct*100:.2f}%) > 2.5% of spot",
                    "strike_guidance": "Market imbalanced; favor strangle / Iron Condor with strikes at VAH/VAL"
                })

        return rules

    def calculate_unified_score(self, osse_score: float, confluence_score: float) -> Dict[str, Any]:
        """
        Combines OSSE Score and Confluence Score using config-driven weights into Unified Score (0-100).
        """
        unified_weights = self.config.get("unified_score_weights", {})
        w_osse = float(unified_weights.get("osse_score_weight", 0.40))
        w_conf = float(unified_weights.get("confluence_score_weight", 0.60))

        unified = w_osse * osse_score + w_conf * confluence_score

        if unified >= 85:
            tier = "Tier 1"
            recommendation = "Full position size (2% capital risk)"
        elif unified >= 65:
            tier = "Tier 2"
            recommendation = "Moderate position size (1% capital risk)"
        elif unified >= 45:
            tier = "Tier 3"
            recommendation = "Paper trade only / reduced size (0.5% capital risk)"
        else:
            tier = "No Trade"
            recommendation = "Skip trade entry"

        return {
            "osse_score": osse_score,
            "confluence_score": confluence_score,
            "unified_score": round(unified, 2),
            "tier": tier,
            "recommendation": recommendation
        }

    def _empty_response(self, reason: str) -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "reason": reason,
            "confluence_score": 0.0,
            "tier": "No Trade",
            "recommended_action": "Skip entirely",
            "components": {},
            "alignment_rules": []
        }
