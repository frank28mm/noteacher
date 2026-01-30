from __future__ import annotations

from homework_agent.core.question_cards import (
    build_question_cards_from_questions_list,
    build_question_cards_from_questions_map,
    infer_answer_state,
    make_card_item_id,
    merge_question_cards,
    sort_question_cards,
)


def test_make_card_item_id_normalizes_question_number():
    assert make_card_item_id(page_index=0, question_number="第1题") == "p1:q:1"
    assert make_card_item_id(page_index=1, question_number="2(1)") == "p2:q:2(1)"


def test_infer_answer_state_prefers_answer_status():
    assert infer_answer_state(student_answer=None, answer_status="未作答") == "blank"
    assert (
        infer_answer_state(student_answer=None, answer_status="已作答") == "has_answer"
    )
    assert infer_answer_state(student_answer=None, answer_status="看不清") == "unknown"


def test_infer_answer_state_student_answer_variants():
    assert infer_answer_state(student_answer=None, answer_status=None) == "unknown"
    assert infer_answer_state(student_answer="  ", answer_status=None) == "blank"
    assert infer_answer_state(student_answer="未作答", answer_status=None) == "blank"
    assert (
        infer_answer_state(
            student_answer="（未提取到，题干/作答请参考 vision_raw_text）",
            answer_status=None,
        )
        == "unknown"
    )
    assert infer_answer_state(student_answer="42", answer_status=None) == "has_answer"


def test_build_cards_from_questions_map_minimal_fields():
    cards = build_question_cards_from_questions_map(
        page_index=0,
        questions={
            "1": {"question_content": "题目：计算 1+1", "student_answer": "未作答"},
            "2": {"question_content": "已知…求证…", "student_answer": "2"},
        },
        card_state="placeholder",
    )
    assert len(cards) == 2
    by_id = {c["item_id"]: c for c in cards}
    assert by_id["p1:q:1"]["answer_state"] == "blank"
    assert by_id["p1:q:2"]["answer_state"] == "has_answer"


def test_build_cards_from_questions_list_includes_verdict_and_blank_count():
    cards, blank_n = build_question_cards_from_questions_list(
        page_index=0,
        questions=[
            {
                "question_number": "1",
                "question_content": "已知…",
                "student_answer": "未作答",
                "verdict": "uncertain",
                "reason": "空题",
            },
            {
                "question_number": "2",
                "question_content": "计算…",
                "student_answer": "2",
                "verdict": "correct",
                "reason": "正确",
            },
        ],
        card_state="verdict_ready",
    )
    assert blank_n == 1
    by_id = {c["item_id"]: c for c in cards}
    assert by_id["p1:q:1"]["answer_state"] == "blank"
    assert by_id["p1:q:2"]["verdict"] == "correct"


def test_merge_and_sort_question_cards():
    merged = merge_question_cards(
        {},
        [
            {
                "item_id": "p2:q:1",
                "question_number": "1",
                "page_index": 1,
                "card_state": "placeholder",
            },
            {
                "item_id": "p1:q:2",
                "question_number": "2",
                "page_index": 0,
                "card_state": "placeholder",
            },
        ],
    )
    merged = merge_question_cards(
        merged,
        [{"item_id": "p1:q:2", "card_state": "verdict_ready", "verdict": "correct"}],
    )
    sorted_cards = sort_question_cards(merged)
    assert [c["item_id"] for c in sorted_cards] == ["p1:q:2", "p2:q:1"]
    assert sorted_cards[0]["verdict"] == "correct"
