from homework_agent.api.chat import _format_math_for_display


def test_format_math_for_display_removes_tilde_and_strikethrough_markers():
    assert "~" not in _format_math_for_display("哈哈~")
    assert "~" not in _format_math_for_display("~~删除线~~")
    assert "删除线" in _format_math_for_display("~~删除线~~")


def test_format_math_for_display_fixes_double_escaped_latex_commands_inside_math():
    s = r"$99\\frac{3}{8} \\times 100\\frac{5}{8}$"
    out = _format_math_for_display(s)
    # De-escape \\frac/\\times and insert thin space between mixed-number integer and fraction.
    assert r"\frac{3}{8}" in out
    assert r"\times" in out
    assert r"99\,\frac{3}{8}" in out
    assert r"100\,\frac{5}{8}" in out
    assert "\\\\frac" not in out


def test_format_math_for_display_converts_programming_style_pow_outside_math():
    s = "把 x^(6n) 改写，再算 y^(2) 。"
    out = _format_math_for_display(s)
    assert "$x^{6n}$" in out
    assert "$y^{2}$" in out

