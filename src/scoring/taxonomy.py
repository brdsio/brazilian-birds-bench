"""Taxonomic distance and error-type classification for wrong answers.

When the model gets a bird name wrong, we want to know *how* wrong:

- Did it confuse two species in the same genus? (intra_genus, distance 1)
- Same family but different genus? (intra_family, distance 2)
- Same order but different family? (intra_order, distance 3)
- Or is the name completely made up? (hallucinated, distance 4)

This module builds a lookup index from the dataset's English names (all three
authorities) to their taxonomy, then uses it to measure the distance between the
model's response and the target species.
"""

from __future__ import annotations

from .normalize import normalize_for_match

TAXONOMY_KEYS = ("genus", "family", "order")
NAME_COLUMNS = ("english_name_cbro", "english_name_ebird", "english_name_avilist")


def build_name_index(dataset_rows: list[dict]) -> dict[str, dict[str, str]]:
    """Map normalized English name -> {genus, family, order} from all authorities.

    Uses all three authority columns so we can look up whatever name the model
    produced, even if it's the eBird or AviList variant.  When the same
    normalized name appears in multiple rows (rare -- would mean two species
    share a common name), the first occurrence wins.
    """
    index: dict[str, dict[str, str]] = {}
    for row in dataset_rows:
        taxonomy = {
            "genus": str(row.get("genus", "")).strip().lower(),
            "family": str(row.get("family", "")).strip().lower(),
            "order": str(row.get("order", "")).strip().lower(),
        }
        for col in NAME_COLUMNS:
            name = normalize_for_match(row.get(col))
            if name and name not in index:
                index[name] = taxonomy
    return index


def taxonomic_distance(
    target_row: dict,
    normalized_response: str,
    name_index: dict[str, dict[str, str]],
) -> int:
    """Measure how far the model's response is from the target species.

    Returns:
        0  match (the scorer already flagged acceptable_match)
        1  same genus, different species (intra_genus)
        2  same family, different genus (intra_family)
        3  same order, different family (intra_order)
        4  different order or name not found in the index (hallucinated)
    """
    if not normalized_response:
        return 4

    response_tax = name_index.get(normalized_response)
    if response_tax is None:
        return 4

    target_genus = str(target_row.get("genus", "")).strip().lower()
    target_family = str(target_row.get("family", "")).strip().lower()
    target_order = str(target_row.get("order", "")).strip().lower()

    if response_tax["genus"] == target_genus and target_genus:
        return 1
    if response_tax["family"] == target_family and target_family:
        return 2
    if response_tax["order"] == target_order and target_order:
        return 3
    return 4


def classify_error(
    target_row: dict,
    normalized_response: str,
    name_index: dict[str, dict[str, str]],
    is_acceptable: bool,
    finish_reason: str,
    truncated: bool = False,
) -> str:
    """Classify the type of error for a benchmark result.

    Returns one of:
        "correct"       acceptable match (exact or any-authority)
        "refusal"       empty response or API error
        "intra_genus"   wrong species, same genus
        "intra_family"  wrong species, same family
        "intra_order"   wrong species, same order
        "hallucinated"  name not found in any known species in the dataset
    """
    if is_acceptable:
        return "correct"

    if finish_reason == "error":
        return "api_error"
    if truncated or finish_reason == "length":
        return "truncated"
    if not normalized_response:
        return "empty_response"

    dist = taxonomic_distance(target_row, normalized_response, name_index)
    return {
        1: "intra_genus",
        2: "intra_family",
        3: "intra_order",
        4: "hallucinated",
    }[dist]
