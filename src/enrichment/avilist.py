"""Enrich the CBRO dataset with English names from AviList.

AviList (https://www.avilist.org) is the first unified global bird checklist,
harmonizing the historical differences between the IOC, Clements/eBird, and
BirdLife taxonomies. It is maintained by the Working Group on Avian Checklists
and released under CC BY 4.0.

    AviList Core Team. 2025. AviList: The Global Avian Checklist, v2025.
    https://doi.org/10.2173/avilist.v2025

Unlike eBird, AviList has no public REST API: it is distributed as an Excel
spreadsheet (Short or Extended) downloaded from the website. So this module
takes a local file path -- just like the CBRO parser -- and needs no token and
no network.

    Short version  (~5 MB): essential taxonomic + name fields. Enough here.
    Extended       (~9 MB): adds nomenclature, bibliography, external links.

The Short spreadsheet has a stable direct URL, so ``bbb`` downloads it
automatically; alternatively the user grabs it from the checklist page and
passes the path with --avilist-file (with --no-download).

IMPORTANT -- column names are resolved flexibly. The exact AviList header
labels were not verified against a live file in this environment; the resolver
below tries a list of known/likely candidates per field and raises a clear
error listing the real columns if none match, so a layout surprise is a
one-line fix rather than a silent wrong-column bug.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

# Candidate column labels per logical field, in priority order. The AviList
# spreadsheets use Title_Case with underscores (e.g. "Taxon_rank", "Order",
# "Family", "Scientific_name", "English_name"); we also accept a few spacing
# and naming variants seen across releases and mirrors.
_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "taxon_rank": ["Taxon_rank", "Taxon rank", "Rank", "taxonRank"],
    "scientific_name": [
        "Scientific_name", "Scientific name", "scientific_name",
        "Species", "Binomial",
    ],
    "english_name": [
        "English_name", "English name", "Common_name", "Common name",
        "English_name_AviList", "english_name",
    ],
    "order": ["Order", "order"],
    "family": ["Family", "family"],
}

SPECIES_RANK = "species"  # value of Taxon_rank for species-level rows

# Columns this module appends to each CBRO record, in output order. Single
# source of truth so the CLI commands never hardcode the list.
AVILIST_FIELDS = [
    "english_name_avilist",
    "avilist_matched",
    "avilist_match_method",  # "binomial" | "epithet_family" | "unmatched"
    "name_disputed_avilist",
]


def _resolve_columns(header: list[str]) -> dict[str, int]:
    """Map each logical field to a column index, using the candidate lists.

    Raises a descriptive KeyError if a required field can't be resolved, so the
    fix (adding the real label to _COLUMN_CANDIDATES) is obvious.
    """
    normalized = {h.strip(): i for i, h in enumerate(header) if h is not None}
    resolved: dict[str, int] = {}
    for field, candidates in _COLUMN_CANDIDATES.items():
        for cand in candidates:
            if cand in normalized:
                resolved[field] = normalized[cand]
                break
        else:
            raise KeyError(
                f"Could not resolve AviList column for {field!r}. "
                f"Tried {candidates}. Actual columns: {list(normalized)}. "
                f"Add the correct label to _COLUMN_CANDIDATES[{field!r}]."
            )
    return resolved


def _normalize_sci(name: str) -> str:
    """Match key: lowercase, collapsed whitespace. Preserves the binomial."""
    return " ".join(str(name).split()).lower()


def _find_data_sheet(wb: openpyxl.Workbook) -> str:
    """Pick the worksheet that actually holds the checklist rows.

    AviList workbooks include a "How to use"/metadata tab plus the data tab
    (commonly named like "AviList v2025"). We choose the first sheet whose
    header resolves cleanly; if none do, we fall back to the first sheet and
    let _resolve_columns raise a clear error.
    """
    for name in wb.sheetnames:
        ws = wb[name]
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not first:
            continue
        header = [str(c) if c is not None else "" for c in first]
        try:
            _resolve_columns(header)
            return name
        except KeyError:
            continue
    return wb.sheetnames[0]


def load_avilist_index(xlsx_path: Path) -> dict[str, dict]:
    """Read the AviList spreadsheet and index species by normalized sci name.

    Returns ``{normalized_sci: {"english_name": ..., "order": ..., "family": ...}}``.
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    sheet = _find_data_sheet(wb)
    ws = wb[sheet]

    rows = ws.iter_rows(values_only=True)
    header = [str(c) if c is not None else "" for c in next(rows)]
    idx = _resolve_columns(header)

    index: dict[str, dict] = {}
    for raw in rows:
        rank = str(raw[idx["taxon_rank"]] or "").strip().lower()
        if rank != SPECIES_RANK:
            continue
        sci = raw[idx["scientific_name"]]
        if not sci:
            continue
        index[_normalize_sci(str(sci))] = {
            "english_name": " ".join(str(raw[idx["english_name"]] or "").split()),
            "order": str(raw[idx["order"]] or "").strip(),
            "family": str(raw[idx["family"]] or "").strip(),
        }
    print(f"  {len(index)} AviList species indexed (sheet {sheet!r}).",
          file=sys.stderr)
    return index


def _epithet_family_index(
    avilist_index: dict[str, dict],
) -> dict[tuple[str, str], list[tuple[str, dict]]]:
    """Secondary index for the fallback pass: ``(epithet, family) -> records``.

    Lets us recover species that CBRO files under a different genus than AviList
    (a genus lump/split, e.g. CBRO ``Aburria jacutinga`` vs AviList ``Pipile
    jacutinga``) but where the epithet and family still agree.
    """
    by_ef: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    for sci_key, rec in avilist_index.items():
        parts = sci_key.split()
        if len(parts) < 2:
            continue
        family = str(rec.get("family") or "").strip().lower()
        if not family:
            continue
        by_ef[(parts[1], family)].append((sci_key, rec))
    return by_ef


def _fallback_lookup(
    row: dict[str, object],
    ef_index: dict[tuple[str, str], list[tuple[str, dict]]],
) -> dict | None:
    """Resolve a CBRO row by (epithet, family) in a *different* genus.

    Returns the AviList record only when the match is unambiguous (exactly one
    distinct target taxon); otherwise None, leaving the row unmatched for manual
    review rather than guessing among homonymous epithets.
    """
    epithet = str(row.get("species_epithet", "")).strip().lower()
    family = str(row.get("family", "")).strip().lower()
    cbro_genus = str(row.get("genus", "")).strip().lower()
    if not (epithet and family):
        return None
    candidates = [
        (sci_key, rec)
        for sci_key, rec in ef_index.get((epithet, family), [])
        if sci_key.split()[0] != cbro_genus
    ]
    distinct = {sci_key for sci_key, _ in candidates}
    if len(distinct) == 1:
        return candidates[0][1]
    return None


def enrich_rows(
    cbro_rows: list[dict[str, object]],
    avilist_index: dict[str, dict],
) -> tuple[list[dict[str, object]], int]:
    """Add AviList columns to each CBRO record. Returns (rows, n_matched).

    Two-pass merge: an exact match on normalized scientific name first, then a
    conservative fallback on ``(epithet, family)`` in a different genus to
    recover genus lumps/splits. ``avilist_match_method`` records which pass won.

    Columns added:
        english_name_avilist   AviList English name (empty if no match)
        avilist_matched         True/False -- matched by either pass
        avilist_match_method    "binomial" | "epithet_family" | "unmatched"
        name_disputed_avilist   True when matched but the English name differs
                                from the CBRO name
    """
    ef_index = _epithet_family_index(avilist_index)
    enriched: list[dict[str, object]] = []
    matched = 0

    for row in cbro_rows:
        sci_key = _normalize_sci(str(row["scientific_name"]))
        av = avilist_index.get(sci_key)
        method = "binomial"
        if av is None:
            av = _fallback_lookup(row, ef_index)
            method = "epithet_family"

        if av is not None:
            matched += 1
            en_av = av["english_name"]
            cbro_en = str(row.get("english_name_cbro", "")).strip()
            disputed = bool(en_av) and (en_av.lower() != cbro_en.lower())
            row = {
                **row,
                "english_name_avilist": en_av,
                "avilist_matched": True,
                "avilist_match_method": method,
                "name_disputed_avilist": disputed,
            }
        else:
            row = {
                **row,
                "english_name_avilist": "",
                "avilist_matched": False,
                "avilist_match_method": "unmatched",
                "name_disputed_avilist": False,
            }
        enriched.append(row)

    return enriched, matched
