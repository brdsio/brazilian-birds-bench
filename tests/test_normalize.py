"""Unit tests for src.scoring.normalize.normalize_for_match."""

from src.scoring import normalize_for_match


def test_lowercases_and_collapses_whitespace():
    assert normalize_for_match("Creamy  BELLIED Thrush") == "creamy bellied thrush"


def test_hyphen_and_space_are_equivalent():
    assert normalize_for_match("Black-fronted Piping-Guan") == normalize_for_match(
        "Black-fronted Piping Guan"
    )


def test_strips_apostrophes_and_punctuation():
    assert normalize_for_match("Swainson's Thrush") == "swainsons thrush"
    assert normalize_for_match("Bare-throated (Tiger) Heron") == (
        "bare throated tiger heron"
    )


def test_slash_is_a_separator():
    assert normalize_for_match("Gray/Grey") == "gray grey"


def test_keeps_genuine_lexical_differences():
    # Spelling variants are NOT folded here -- that is a separate concern.
    assert normalize_for_match("Gray Tinamou") != normalize_for_match("Grey Tinamou")


def test_empty_and_none():
    assert normalize_for_match("") == ""
    assert normalize_for_match(None) == ""
    assert normalize_for_match("   ") == ""


def test_idempotent():
    once = normalize_for_match("Rufous-tailed Jacamar")
    assert normalize_for_match(once) == once
