from src.scoring.taxonomy import classify_error


def test_transport_and_generation_failures_are_distinct():
    args = ({}, "", {}, False)
    assert classify_error(*args, "error") == "api_error"
    assert classify_error(*args, "length", truncated=True) == "truncated"
    assert classify_error(*args, "stop") == "empty_response"


def test_truncation_takes_precedence_over_empty_response():
    assert classify_error({}, "", {}, False, "stop", truncated=True) == "truncated"
