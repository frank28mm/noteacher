"""
Unit tests for grade.py utility functions.
Tests image validation, URL parsing, and grading utilities.
"""

import pytest
from unittest.mock import MagicMock

from homework_agent.api.grade import (
    _is_public_url,
    _strip_base64_prefix,
    _normalize_public_url,
    validate_images_payload,
    generate_job_id,
    _bank_has_visual_risk,
)
from homework_agent.models.schemas import VisionProvider, ImageRef



class TestIsPublicUrl:
    """Tests for _is_public_url function."""

    def test_http_urls(self):
        """Should return True for http/https URLs."""
        assert _is_public_url("https://example.com/image.jpg") is True
        assert _is_public_url("http://example.com/image.jpg") is True

    def test_non_http_strings(self):
        """Should return False for non-http strings."""
        assert _is_public_url("data:image/png;base64,xxx") is False
        assert _is_public_url("file:///path/to/image.jpg") is False
        assert _is_public_url("") is False
        assert _is_public_url("not a url") is False


class TestStripBase64Prefix:
    """Tests for _strip_base64_prefix function."""

    def test_with_prefix(self):
        """Should strip data: prefix."""
        result = _strip_base64_prefix("data:image/png;base64,ABC123")
        assert result == "ABC123"

    def test_without_prefix(self):
        """Should return unchanged if no prefix."""
        assert _strip_base64_prefix("ABC123") == "ABC123"


class TestNormalizePublicUrl:
    """Tests for _normalize_public_url function."""

    def test_valid_url(self):
        """Should return cleaned URL."""
        result = _normalize_public_url("  https://example.com/image.jpg  ")
        assert result == "https://example.com/image.jpg"

    def test_none_input(self):
        """Should return None for None input."""
        assert _normalize_public_url(None) is None

    def test_empty_string(self):
        """Should return None for empty string."""
        assert _normalize_public_url("") is None
        assert _normalize_public_url("   ") is None


class TestGenerateJobId:
    """Tests for generate_job_id function."""

    def test_format(self):
        """Should generate job IDs with correct format."""
        job_id = generate_job_id()
        assert job_id.startswith("job_")
        assert len(job_id) > 4

    def test_uniqueness(self):
        """Should generate unique IDs."""
        ids = [generate_job_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestValidateImagesPayload:
    """Tests for validate_images_payload function."""

    def test_empty_images_raises(self):
        """Should raise for empty images list."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            validate_images_payload([], VisionProvider.QWEN3)
        assert exc_info.value.status_code == 400

    def test_valid_url_image(self):
        """Should not raise for valid URL image."""
        images = [{"url": "https://example.com/image.jpg"}]
        validate_images_payload(images, VisionProvider.QWEN3)  # Should not raise

    def test_doubao_rejects_raw_base64(self):
        """Doubao should reject raw base64 (without data: prefix)."""
        from fastapi import HTTPException
        images = [{"base64": "ABC123notdataurl"}]
        with pytest.raises(HTTPException) as exc_info:
            validate_images_payload(images, VisionProvider.DOUBAO)
        assert exc_info.value.status_code == 400


class TestBankHasVisualRisk:
    """Tests for _bank_has_visual_risk function."""

    def test_empty_bank(self):
        """Should return False for empty bank."""
        assert _bank_has_visual_risk({}) is False
        assert _bank_has_visual_risk(None) is False

    def test_bank_with_visual_risk(self):
        """Should return True when visual_risk is set."""
        bank = {
            "questions": {
                "1": {"visual_risk": True},
                "2": {"visual_risk": False},
            }
        }
        assert _bank_has_visual_risk(bank) is True

    def test_bank_without_visual_risk(self):
        """Should return False when no visual_risk set."""
        bank = {
            "questions": {
                "1": {"content": "text only"},
            }
        }
        assert _bank_has_visual_risk(bank) is False
