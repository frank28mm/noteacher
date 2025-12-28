from homework_agent.services import vision_facts as vf


def test_normalize_tokens_angle_variants():
    assert "ANGLE_2" in vf._normalize_tokens("∠2 在哪里")
    assert "ANGLE_2" in vf._normalize_tokens("角2 在哪里")
    assert "ANGLE_2" in vf._normalize_tokens("angle 2 where is it")
    assert "ANGLE_1" in vf._normalize_tokens("∠1=150°")
    assert "ANGLE_BCD" in vf._normalize_tokens("∠BCD=30°")


def test_normalize_tokens_segment_variants():
    assert "CD" in vf._normalize_tokens("CD 在哪")
    assert "CD" in vf._normalize_tokens("DC 在哪")  # DC normalized to CD
    assert "AD" in vf._normalize_tokens("AD 水平")
    assert "BC" in vf._normalize_tokens("BC 水平")
    assert "AB" in vf._normalize_tokens("AB 竖直")


def test_normalize_tokens_position_words():
    assert "ABOVE" in vf._normalize_tokens("在AD上方")
    assert "ABOVE" in vf._normalize_tokens("在AD上面")
    assert "ABOVE" in vf._normalize_tokens("在AD上侧")
    assert "BELOW" in vf._normalize_tokens("在BC下方")
    assert "LEFT" in vf._normalize_tokens("在CD左侧")
    assert "LEFT" in vf._normalize_tokens("在CD左边")
    assert "RIGHT" in vf._normalize_tokens("在CD右侧")
    assert "RIGHT" in vf._normalize_tokens("在CD右边")


def test_normalize_tokens_diagram_missing():
    assert "DIAGRAM_MISSING" in vf._normalize_tokens("diagram_missing")
    assert "DIAGRAM_MISSING" in vf._normalize_tokens("未见图形区域")
