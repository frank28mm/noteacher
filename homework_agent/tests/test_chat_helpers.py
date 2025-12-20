"""
Unit tests for chat.py helper functions.
Tests visual check detection and math formatting for display.
"""

from homework_agent.api.chat import (
    _user_requests_visual_check,
    _format_math_for_display,
)


class TestUserRequestsVisualCheck:
    """Tests for _user_requests_visual_check function."""

    def test_explicit_visual_keywords(self):
        """Should return True for explicit 'look at image' keywords."""
        assert _user_requests_visual_check("看图") is True
        assert _user_requests_visual_check("如图所示") is True
        assert _user_requests_visual_check("见图") is True
        assert _user_requests_visual_check("你看不到图") is True

    def test_geometry_keywords(self):
        """Should return True for geometry-related keywords."""
        assert _user_requests_visual_check("三角形ABC") is True
        assert _user_requests_visual_check("平行四边形") is True
        assert _user_requests_visual_check("正方形的边长") is True
        assert _user_requests_visual_check("矩形面积") is True

    def test_chart_keywords(self):
        """Should return True for chart/diagram keywords."""
        assert _user_requests_visual_check("统计图") is True
        assert _user_requests_visual_check("折线图") is True
        assert _user_requests_visual_check("柱状图") is True
        assert _user_requests_visual_check("表格") is True

    def test_non_visual_messages(self):
        """Should return False for non-visual messages."""
        assert _user_requests_visual_check("这道题怎么做") is False
        assert _user_requests_visual_check("我不理解") is False
        assert _user_requests_visual_check("") is False
        assert _user_requests_visual_check("计算x的值") is False


class TestFormatMathForDisplay:
    """Tests for _format_math_for_display function."""

    def test_basic_text_passthrough(self):
        """Should return plain text unchanged."""
        assert _format_math_for_display("Hello world") == "Hello world"
        assert _format_math_for_display("") == ""

    def test_latex_delimiter_removal(self):
        """Should remove common LaTeX delimiters."""
        # Basic inline math
        result = _format_math_for_display(r"The answer is \(x^2\)")
        assert r"\(" not in result
        assert r"\)" not in result

    def test_tilde_removal(self):
        """Should remove tildes (banned in output)."""
        assert "~" not in _format_math_for_display("x ~ y")
        assert "～" not in _format_math_for_display("x～y")

    def test_error_handling(self):
        """Should not raise on invalid input."""
        # Function converts None to string "None" or similar - should not crash
        try:
            result = _format_math_for_display(None)  # type: ignore
            # If it doesn't crash, test passes (result could be None or "None")
            assert True
        except Exception:
            assert False, "Should not raise exception"

