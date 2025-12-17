"""
Unit tests for session.py functions.
Tests session management, caching, and timestamp handling.
"""

import pytest
from datetime import datetime

from homework_agent.api.session import (
    _ensure_session_id,
    _now_ts,
    _coerce_ts,
    _merge_bank_meta,
)


class TestEnsureSessionId:
    """Tests for _ensure_session_id function."""

    def test_returns_existing_id(self):
        """Should return the existing session_id if provided."""
        assert _ensure_session_id("existing-session") == "existing-session"
        assert _ensure_session_id("  padded  ") == "padded"

    def test_generates_new_id(self):
        """Should generate a new ID if none provided."""
        result = _ensure_session_id(None)
        assert result.startswith("session_")
        assert len(result) > 8

    def test_empty_string_generates_new(self):
        """Should treat empty string as missing."""
        result = _ensure_session_id("")
        assert result.startswith("session_")

        result2 = _ensure_session_id("   ")
        assert result2.startswith("session_")


class TestNowTs:
    """Tests for _now_ts function."""

    def test_returns_float(self):
        """Should return current timestamp as float."""
        ts = _now_ts()
        assert isinstance(ts, float)
        assert ts > 0


class TestCoerceTs:
    """Tests for _coerce_ts function."""

    def test_none_input(self):
        """Should return None for None input."""
        assert _coerce_ts(None) is None

    def test_float_input(self):
        """Should return float unchanged."""
        ts = 1234567890.123
        assert _coerce_ts(ts) == ts

    def test_int_input(self):
        """Should convert int to float."""
        assert _coerce_ts(1234567890) == 1234567890.0

    def test_datetime_input(self):
        """Should convert datetime to timestamp."""
        dt = datetime(2023, 1, 1, 12, 0, 0)
        result = _coerce_ts(dt)
        assert isinstance(result, float)
        assert result > 0

    def test_string_float(self):
        """Should parse string float."""
        assert _coerce_ts("1234567890.5") == 1234567890.5

    def test_iso_string(self):
        """Should parse ISO datetime string."""
        result = _coerce_ts("2023-01-01T12:00:00")
        assert isinstance(result, float)
        assert result > 0

    def test_invalid_string(self):
        """Should return None for invalid string."""
        assert _coerce_ts("not a timestamp") is None
        assert _coerce_ts("") is None


class TestMergeBankMeta:
    """Tests for _merge_bank_meta function."""

    def test_adds_meta_to_empty_bank(self):
        """Should add meta to bank without existing meta."""
        bank = {"questions": {}}
        extra = {"key": "value"}
        result = _merge_bank_meta(bank, extra)
        assert result["meta"]["key"] == "value"

    def test_merges_with_existing_meta(self):
        """Should merge with existing meta."""
        bank = {"meta": {"existing": "old"}}
        extra = {"new": "value"}
        result = _merge_bank_meta(bank, extra)
        assert result["meta"]["existing"] == "old"
        assert result["meta"]["new"] == "value"

    def test_skips_none_values(self):
        """Should not include None values in merge."""
        bank = {"meta": {}}
        extra = {"keep": "value", "skip": None}
        result = _merge_bank_meta(bank, extra)
        assert result["meta"]["keep"] == "value"
        assert "skip" not in result["meta"]

    def test_non_dict_returns_unchanged(self):
        """Should return unchanged for non-dict input."""
        assert _merge_bank_meta(None, {}) is None
        assert _merge_bank_meta("not a dict", {}) == "not a dict"
