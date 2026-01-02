import pytest

import homework_agent.api._chat_stages as chat_stages
from homework_agent.api.chat import _ChatAbort
from homework_agent.models.schemas import ChatRequest, Subject


def _stub_qbank(monkeypatch: pytest.MonkeyPatch):
    qbank = {
        "questions": {
            "20": {
                "question_content": "题干",
                "visual_risk": False,
            }
        },
        "page_image_urls": [],
    }
    monkeypatch.setattr(chat_stages, "get_question_bank", lambda session_id: qbank)
    monkeypatch.setattr(chat_stages, "get_question_index", lambda session_id: None)
    monkeypatch.setattr(
        chat_stages, "save_question_bank", lambda session_id, qbank_now: None
    )
    monkeypatch.setattr(
        chat_stages, "analyze_visual_risk", lambda *args, **kwargs: (False, None)
    )
    monkeypatch.setattr(
        chat_stages.chat_api, "qindex_is_configured", lambda: (False, "test")
    )
    return qbank


def test_focus_retained_when_no_new_question_number(monkeypatch: pytest.MonkeyPatch):
    _stub_qbank(monkeypatch)
    session_data = {
        "history": [],
        "interaction_count": 0,
        "focus_question_number": "20",
    }
    req = ChatRequest(
        history=[],
        question="再讲一下这个步骤",
        subject=Subject.MATH,
        session_id="sess_focus_keep",
        context_item_ids=[],
    )

    ctx = chat_stages._prepare_chat_context_or_abort(
        req=req,
        session_id="sess_focus_keep",
        request_id="req_focus_keep",
        user_id="user",
        session_data=session_data,
    )

    assert ctx["focus_question_number"] == "20"


def test_focus_switch_without_target_prompts_user(monkeypatch: pytest.MonkeyPatch):
    _stub_qbank(monkeypatch)
    session_data = {
        "history": [],
        "interaction_count": 0,
        "focus_question_number": "20",
    }
    req = ChatRequest(
        history=[],
        question="换一题",
        subject=Subject.MATH,
        session_id="sess_focus_switch",
        context_item_ids=[],
    )

    with pytest.raises(_ChatAbort):
        chat_stages._prepare_chat_context_or_abort(
            req=req,
            session_id="sess_focus_switch",
            request_id="req_focus_switch",
            user_id="user",
            session_data=session_data,
        )
