from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class FlagDecision:
    enabled: bool
    variant: Optional[str] = None
    reason: str = "default"


def _stable_bucket(key: str, *, salt: str) -> float:
    """
    Stable bucket in [0, 100).
    Deterministic across processes for the same key+salt.
    """
    raw = (str(salt or "") + "|" + str(key or "")).encode("utf-8", errors="ignore")
    h = hashlib.sha256(raw).hexdigest()
    n = int(h[:8], 16)
    return (n % 10000) / 100.0


def _load_flags(json_text: str) -> Dict[str, Any]:
    if not json_text:
        return {}
    try:
        data = json.loads(json_text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def decide(
    *,
    flags_json: str,
    name: str,
    key: str,
    salt: str,
) -> FlagDecision:
    """
    Supported config shapes in flags_json:
      {"flag_name": true}
      {"flag_name": {"enabled": true}}
      {"flag_name": {"enabled": true, "rollout_pct": 10}}
      {"exp_name": {"enabled": true, "rollout_pct": 50, "variants": {"A": 50, "B": 50}}}
    """
    cfg = _load_flags(flags_json).get(str(name or "").strip())
    if cfg is True:
        return FlagDecision(enabled=True, reason="static_true")
    if cfg is False:
        return FlagDecision(enabled=False, reason="static_false")
    if not isinstance(cfg, dict):
        return FlagDecision(enabled=False, reason="missing")

    enabled = bool(cfg.get("enabled", False))
    if not enabled:
        return FlagDecision(enabled=False, reason="disabled")

    rollout_pct = cfg.get("rollout_pct")
    if rollout_pct is None:
        rollout_pct = 100
    try:
        rollout_pct = float(rollout_pct)
    except Exception:
        rollout_pct = 100.0
    rollout_pct = max(0.0, min(100.0, rollout_pct))

    b = _stable_bucket(key, salt=salt)
    if b >= rollout_pct:
        return FlagDecision(enabled=False, reason=f"rollout_excluded:{b:.2f}")

    variants = cfg.get("variants")
    if isinstance(variants, dict) and variants:
        total = 0.0
        items: list[Tuple[str, float]] = []
        for k, v in variants.items():
            try:
                w = float(v)
            except Exception:
                continue
            if w <= 0:
                continue
            total += w
            items.append((str(k), w))
        if total > 0 and items:
            vb = _stable_bucket(key + "|variant:" + name, salt=salt) * total / 100.0
            acc = 0.0
            for variant, weight in items:
                acc += weight
                if vb <= acc:
                    return FlagDecision(
                        enabled=True,
                        variant=variant,
                        reason=f"rollout_included:{b:.2f}",
                    )
            return FlagDecision(
                enabled=True, variant=items[-1][0], reason=f"rollout_included:{b:.2f}"
            )

    return FlagDecision(enabled=True, reason=f"rollout_included:{b:.2f}")
