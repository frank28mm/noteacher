from __future__ import annotations

from unittest.mock import MagicMock, patch

from homework_agent.services.context_compactor import (
    _deterministic_summary,
    summarize_history,
    compact_session_history,
)


def test_deterministic_summary_empty_history() -> None:
    result = _deterministic_summary([])
    assert result == ""


def test_deterministic_summary_returns_formatted_text() -> None:
    history = [
        {"role": "user", "content": "第一题是1+1等于几"},
        {"role": "assistant", "content": "1+1等于2"},
        {"role": "user", "content": "第二题是2+2等于几"},
        {"role": "assistant", "content": "2+2等于4"},
    ]
    result = _deterministic_summary(history)
    assert "用户" in result
    assert "助理" in result
    assert "1+1" in result
    assert len(result) <= 200


def test_deterministic_summary_truncates_to_max_chars() -> None:
    history = [
        {"role": "user", "content": "x" * 100},
        {"role": "assistant", "content": "y" * 100},
        {"role": "user", "content": "z" * 100},
        {"role": "assistant", "content": "w" * 100},
    ]
    result = _deterministic_summary(history, max_chars=50)
    assert len(result) <= 51  # max_chars + "…"


def test_deterministic_summary_keeps_recent_turns() -> None:
    history = [{"role": "user", "content": f"消息{i}"} for i in range(10)]
    history.append({"role": "assistant", "content": "最新回复"})

    result = _deterministic_summary(history)
    # Should keep last 6 messages
    assert "最新回复" in result


def test_deterministic_summary_ignores_non_dict_messages() -> None:
    history = [
        {"role": "user", "content": "正常消息"},
        None,
        "invalid",
        {"role": "assistant", "content": "回复"},
    ]
    result = _deterministic_summary(history)
    assert "正常消息" in result
    assert "回复" in result


def test_summarize_history_empty_history() -> None:
    result = summarize_history([])
    assert result == ""


def test_summarize_history_without_role() -> None:
    history = [
        {"content": "没有role的消息"},
    ]
    result = summarize_history(history)
    # Should handle gracefully - may return empty or partial
    assert isinstance(result, str)


@patch("homework_agent.services.context_compactor.LLMClient")
def test_summarize_history_calls_llm(mock_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.text = "这是LLM生成的摘要"
    mock_client = MagicMock()
    mock_client.generate.return_value = mock_response
    mock_client_class.return_value = mock_client

    history = [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "助手回答"},
    ]

    result = summarize_history(history, provider="test_provider")
    assert result == "这是LLM生成的摘要"
    mock_client.generate.assert_called_once()


@patch("homework_agent.services.context_compactor.LLMClient")
def test_summarize_history_handles_llm_failure(mock_client_class: MagicMock) -> None:
    mock_client = MagicMock()
    mock_client.generate.side_effect = Exception("LLM failed")
    mock_client_class.return_value = mock_client

    history = [{"role": "user", "content": "测试"}]

    result = summarize_history(history)
    assert result == ""  # Should return empty on error


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_disabled_by_settings(
    mock_get_settings: MagicMock,
) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "off"
    mock_get_settings.return_value = mock_settings

    session_data = {
        "history": [{"role": "user", "content": "message"}] * 30,
    }

    result = compact_session_history(session_data)
    assert result is False
    assert session_data.get("summary") is None


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_not_enough_messages(
    mock_get_settings: MagicMock,
) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "deterministic"
    mock_settings.context_compaction_max_messages = 24
    mock_settings.context_compaction_interval = 8
    mock_get_settings.return_value = mock_settings

    session_data = {
        "history": [{"role": "user", "content": "message"}] * 10,  # Less than max
    }

    result = compact_session_history(session_data)
    assert result is False


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_deterministic_mode(
    mock_get_settings: MagicMock,
) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "deterministic"
    mock_settings.context_compaction_enabled = False
    mock_settings.context_compaction_max_messages = 10
    mock_settings.context_compaction_overlap = 3
    mock_settings.context_compaction_interval = 5
    mock_get_settings.return_value = mock_settings

    # Need 15 messages to trigger compaction: > max_messages (10) and % interval (5) == 0
    session_data = {
        "history": [{"role": "user", "content": f"消息{i}"} for i in range(15)],
    }

    result = compact_session_history(session_data, provider="test_provider")
    assert result is True
    assert "summary" in session_data
    assert len(session_data["history"]) <= 3  # overlap size
    assert session_data["summary"] != ""


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_checks_interval(mock_get_settings: MagicMock) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "deterministic"
    mock_settings.context_compaction_max_messages = 10
    mock_settings.context_compaction_overlap = 3
    mock_settings.context_compaction_interval = 8
    mock_get_settings.return_value = mock_settings

    # 13 messages but 13 % 8 != 0, so no compaction
    session_data = {
        "history": [{"role": "user", "content": f"消息{i}"} for i in range(13)],
    }

    result = compact_session_history(session_data)
    assert result is False


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_invalid_mode_defaults_to_deterministic(
    mock_get_settings: MagicMock,
) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "invalid_mode"
    mock_settings.context_compaction_enabled = False
    mock_settings.context_compaction_max_messages = 10
    mock_settings.context_compaction_overlap = 3
    mock_settings.context_compaction_interval = 5
    mock_get_settings.return_value = mock_settings

    # Need 15 messages to trigger compaction
    session_data = {
        "history": [{"role": "user", "content": f"消息{i}"} for i in range(15)],
    }

    result = compact_session_history(session_data)
    # Should fall back to deterministic and compact
    assert result is True


@patch("homework_agent.services.context_compactor.get_settings")
def test_compact_session_history_llm_mode_without_enabled(
    mock_get_settings: MagicMock,
) -> None:
    mock_settings = MagicMock()
    mock_settings.context_compaction_mode = "llm"
    mock_settings.context_compaction_enabled = False  # LLM not enabled
    mock_settings.context_compaction_max_messages = 10
    mock_settings.context_compaction_overlap = 3
    mock_settings.context_compaction_interval = 5
    mock_get_settings.return_value = mock_settings

    # Need 15 messages to trigger compaction
    session_data = {
        "history": [{"role": "user", "content": f"消息{i}"} for i in range(15)],
    }

    result = compact_session_history(session_data, provider="test_provider")
    # Should use deterministic (LLM mode but not enabled)
    assert result is True


def test_compact_session_history_handles_invalid_history() -> None:
    session_data = {
        "history": "not_a_list",
    }

    result = compact_session_history(session_data)
    assert result is False


def test_compact_session_history_handles_missing_history() -> None:
    session_data = {}

    result = compact_session_history(session_data)
    assert result is False
