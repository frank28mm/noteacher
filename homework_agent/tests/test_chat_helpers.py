"""
Unit tests for chat.py helper functions.
Tests visual check detection and math formatting for display.
"""

from homework_agent.api.chat import (
    _user_requests_visual_check,
    _format_math_for_display,
    _should_relook_focus_question,
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


class TestShouldRelookFocusQuestion:
    """Tests for _should_relook_focus_question function."""

    def test_explicit_relook_triggers(self):
        """Should return True when user challenges recognition."""
        assert _should_relook_focus_question("题目不对", {}) is True
        assert _should_relook_focus_question("识别错了", {}) is True
        assert _should_relook_focus_question("看图", {}) is True

    def test_already_relooked_skip(self):
        """Should return False if already relooked (unless explicit challenge)."""
        focus = {"vision_recheck_text": "already did it"}
        # Explicit challenge should still trigger
        assert _should_relook_focus_question("识别错了", focus) is True
        # Non-challenge should skip
        assert _should_relook_focus_question("继续讲", focus) is False

    def test_non_visual_message_skip(self):
        """Should return False for regular non-visual messages."""
        assert _should_relook_focus_question("这题怎么做", {}) is False
        assert _should_relook_focus_question("讲讲第3题", {}) is False
