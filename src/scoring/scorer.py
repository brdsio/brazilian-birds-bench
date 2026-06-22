"""Score benchmark results: exact match, acceptable match, and error classification.

Three layers:

1. **Exact match** (primary) -- the model's normalized response equals the CBRO
   English name.

2. **Acceptable match** (secondary) -- the normalized response equals the
   English name from *any* of the three authorities (CBRO, eBird, AviList).
   ``match_source`` records which authorities agreed.

3. **Error classification** -- for wrong answers, ``error_type`` says *how*
   wrong (same genus? same family? hallucinated?) and ``taxonomic_distance``
   gives the numeric distance (0–4).
"""

from __future__ import annotations

from .normalize import normalize_for_match
from .taxonomy import build_name_index, classify_error, taxonomic_distance

AUTHORITY_COLUMNS: dict[str, str] = {
    "cbro": "english_name_cbro",
    "ebird": "english_name_ebird",
    "avilist": "english_name_avilist",
}


def score_row(
    row: dict[str, object],
    name_index: dict[str, dict[str, str]],
) -> dict[str, object]:
    """Score a single benchmark result and return the row with score columns."""
    response = normalize_for_match(row.get("model_response"))
    target = normalize_for_match(row.get("english_name_cbro"))

    exact = response != "" and response == target

    sources: list[str] = []
    if response:
        for source_name, col_name in AUTHORITY_COLUMNS.items():
            ref = normalize_for_match(row.get(col_name))
            if ref and response == ref:
                sources.append(source_name)

    acceptable = len(sources) > 0

    dist = 0 if acceptable else taxonomic_distance(row, response, name_index)
    error = classify_error(
        row, response, name_index, acceptable,
        str(row.get("finish_reason", "")),
    )

    return {
        **row,
        "normalized_response": response,
        "normalized_target": target,
        "exact_match": exact,
        "acceptable_match": acceptable,
        "match_source": ";".join(sources),
        "taxonomic_distance": dist,
        "error_type": error,
    }


def score_results(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Score all benchmark result rows."""
    name_index = build_name_index(rows)
    return [score_row(row, name_index) for row in rows]
