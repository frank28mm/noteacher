from __future__ import annotations

from homework_agent.core.review_cards_policy import pick_review_candidates
from homework_agent.models.schemas import Subject


def test_pick_review_candidates_filters_blank_and_non_visual_risk():
    qs = [
        {
            "question_number": "1",
            "verdict": "uncertain",
            "question_content": "计算 1+1",
            "student_answer": "2",
            "warnings": [],
        },
        {
            "question_number": "2",
            "verdict": "uncertain",
            "question_content": "如图，∠ABC 与 ∠DEF 的关系是？",
            "student_answer": "未作答",
            "warnings": [],
        },
        {
            "question_number": "3",
            "verdict": "uncertain",
            "question_content": "如图，已知两条平行线…求角度",
            "student_answer": "30°",
            "warnings": ["needs_review"],
        },
    ]
    cands = pick_review_candidates(
        subject=Subject.MATH, page_index=0, questions=qs, max_per_page=5
    )
    # q1 is not visually risky; q2 is blank; only q3 remains
    assert [c.question_number for c in cands] == ["3"]
    assert cands[0].item_id == "p1:q:3"


def test_pick_review_candidates_prioritizes_uncertain_then_incorrect():
    qs = [
        {
            "question_number": "1",
            "verdict": "incorrect",
            "question_content": "如图，判断同位角/内错角",
            "student_answer": "同位角",
            "warnings": ["needs_review"],
        },
        {
            "question_number": "2",
            "verdict": "uncertain",
            "question_content": "如图，求∠A 的度数",
            "student_answer": "50",
            "warnings": [],
        },
    ]
    cands = pick_review_candidates(
        subject=Subject.MATH, page_index=1, questions=qs, max_per_page=2
    )
    assert [c.question_number for c in cands] == ["2", "1"]
    assert cands[0].priority < cands[1].priority

