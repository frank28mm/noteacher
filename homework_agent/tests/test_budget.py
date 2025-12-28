from homework_agent.utils.budget import RunBudget, extract_total_tokens


def test_extract_total_tokens_from_dict():
    assert extract_total_tokens({"total_tokens": 12}) == 12
    assert extract_total_tokens({"total_tokens": "12"}) == 12
    assert extract_total_tokens({"prompt_tokens": 1}) is None


def test_budget_consumes_tokens_and_detects_exhaustion():
    b = RunBudget.for_timeout_seconds(timeout_seconds=10, token_budget_total=5)
    assert not b.is_token_exhausted()
    b.consume_usage({"total_tokens": 3})
    assert b.tokens_used == 3
    assert not b.is_token_exhausted()
    b.consume_usage({"total_tokens": 3})
    assert b.tokens_used == 6
    assert b.is_token_exhausted()
