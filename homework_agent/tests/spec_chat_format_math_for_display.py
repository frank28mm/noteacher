from homework_agent.api.chat import _format_math_for_display


def test_format_math_for_display_removes_tilde_and_strikethrough_markers():
    assert "~" not in _format_math_for_display("哈哈~")
    assert "~" not in _format_math_for_display("~~删除线~~")
    assert "删除线" in _format_math_for_display("~~删除线~~")



