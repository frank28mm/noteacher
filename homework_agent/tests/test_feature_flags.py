from __future__ import annotations

from homework_agent.utils.feature_flags import decide


def test_feature_flag_static_true_false() -> None:
    flags = '{"a": true, "b": false}'
    assert decide(flags_json=flags, name="a", key="u1", salt="s").enabled is True
    assert decide(flags_json=flags, name="b", key="u1", salt="s").enabled is False
    assert decide(flags_json=flags, name="missing", key="u1", salt="s").enabled is False


def test_feature_flag_rollout_is_stable() -> None:
    flags = '{"exp": {"enabled": true, "rollout_pct": 10}}'
    d1 = decide(flags_json=flags, name="exp", key="user_123", salt="salt")
    d2 = decide(flags_json=flags, name="exp", key="user_123", salt="salt")
    assert d1.enabled == d2.enabled
    assert d1.reason == d2.reason


def test_feature_flag_variants_are_deterministic() -> None:
    flags = (
        '{"ab": {"enabled": true, "rollout_pct": 100, "variants": {"A": 50, "B": 50}}}'
    )
    d1 = decide(flags_json=flags, name="ab", key="user_1", salt="salt")
    d2 = decide(flags_json=flags, name="ab", key="user_1", salt="salt")
    assert d1.enabled is True and d2.enabled is True
    assert d1.variant == d2.variant
    assert d1.variant in {"A", "B"}
