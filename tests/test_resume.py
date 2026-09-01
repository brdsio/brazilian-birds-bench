import pytest
from click import ClickException

from src.cli import _index_resume_rows


def _row(cbro_id: str) -> dict[str, str]:
    return {
        "cbro_id": cbro_id,
        "model": "vendor/model",
        "benchmark_mode": "no_reasoning",
        "reasoning_config": '{"effort": "none"}',
    }


def test_resume_is_indexed_by_stable_id_not_position():
    indexed = _index_resume_rows(
        [_row("CBRO#2"), _row("CBRO#1")],
        "vendor/model",
        "no_reasoning",
        {"effort": "none"},
    )
    assert list(indexed) == ["CBRO#2", "CBRO#1"]
    assert indexed["CBRO#1"]["cbro_id"] == "CBRO#1"


def test_resume_rejects_duplicate_species():
    with pytest.raises(ClickException, match="Duplicate cbro_id"):
        _index_resume_rows(
            [_row("CBRO#1"), _row("CBRO#1")],
            "vendor/model",
            "no_reasoning",
            {"effort": "none"},
        )
