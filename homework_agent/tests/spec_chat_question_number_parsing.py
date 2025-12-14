from homework_agent.api.chat import _extract_requested_question_number


def test_extract_requested_question_number_bare_token():
    assert _extract_requested_question_number("20(2)") == "20(2)"
    assert _extract_requested_question_number("  28(1)②  ") == "28(1)②"
    assert _extract_requested_question_number("27") == "27"
    assert _extract_requested_question_number("20（1）") == "20(1)"


def test_extract_requested_question_number_with_context_words():
    assert _extract_requested_question_number("讲讲第20(2)题") == "20(2)"
    assert _extract_requested_question_number("聊 28(1)②") == "28(1)②"
    assert _extract_requested_question_number("第8题我不会") == "8"
    assert _extract_requested_question_number("题 16 怎么做") == "16"
    assert _extract_requested_question_number("请为我讲解20题的第一小题") == "20(1)"
    assert _extract_requested_question_number("二十题第一小题") == "20(1)"
    assert _extract_requested_question_number("你给我讲讲20题的第二小题呗") == "20(2)"
    assert _extract_requested_question_number("我的20(3)是哪里有问题？") == "20(3)"


def test_extract_requested_question_number_avoids_math_expression_numbers():
    assert _extract_requested_question_number("t(t-8)+16?") is None
    assert _extract_requested_question_number("(x^2+x)(x^2+x-8)+16") is None
