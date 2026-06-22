"""Enrich the CBRO dataset with English names from eBird/Clements.

Strategy: instead of one call per species (slow and abusive to the API), we
download the entire eBird taxonomy in a single request and merge locally by
scientific name. The eBird API 2.0 requires a token, sent in the
``x-ebirdapitoken`` header; get yours at https://ebird.org/api/keygen.

Endpoint: GET https://api.ebird.org/v2/ref/taxonomy/ebird?fmt=json
    Relevant fields per record:
        sciName        scientific name
        comName        common name (English by default; locale changes language)
        speciesCode    unique eBird alphanumeric code
        category       'species' | 'subspecies' | 'hybrid' | 'spuh' | ...
        familySciName  family (scientific), when present
        order          order

The merge is done by normalized scientific name. Where CBRO and eBird use
different scientific names for the same taxon (synonymy, splits/lumps), the
match fails -- and that is valuable data, not an error: we flag the species as
``ebird_matched = False`` for review and as a ``name_disputed`` candidate.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests

EBIRD_TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird"
ENV_TOKEN = "EBIRD_API_TOKEN"

# Columns this module appends to each CBRO record, in output order. Single
# source of truth so the CLI commands never hardcode the list.
EBIRD_FIELDS = [
    "english_name_ebird",
    "ebird_species_code",
    "ebird_matched",
    "ebird_match_method",  # "binomial" | "epithet_family" | "unmatched"
    "name_disputed",
]


def _normalize_sci(name: str) -> str:
    """Match key: lowercase, collapsed whitespace. Preserves the binomial.

    We do not strip epithets or authorship because CBRO already provides the
    name without authorship; we only standardize case and whitespace for the
    lookup.
    """
    return " ".join(str(name).split()).lower()


def fetch_ebird_taxonomy(token: str, locale: str = "en") -> dict[str, dict]:
    """Download the entire eBird taxonomy and index it by normalized sci name.

    Returns only 'species'-category records (which is what CBRO lists at the
    species level). Returns ``{normalized_sci: ebird_record}``.
    """
    headers = {"x-ebirdapitoken": token}
    params = {"fmt": "json", "locale": locale, "cat": "species"}
    print("Downloading eBird taxonomy (single request)...", file=sys.stderr)
    resp = requests.get(EBIRD_TAXONOMY_URL, headers=headers, params=params,
                        timeout=120)
    resp.raise_for_status()
    data = resp.json()

    index: dict[str, dict] = {}
    for rec in data:
        if rec.get("category") != "species":
            continue
        sci = rec.get("sciName")
        if not sci:
            continue
        index[_normalize_sci(sci)] = rec
    print(f"  {len(index)} eBird species indexed.", file=sys.stderr)
    return index


def _epithet_family_index(
    ebird_index: dict[str, dict],
) -> dict[tuple[str, str], list[tuple[str, dict]]]:
    """Secondary index for the fallback pass: ``(epithet, family) -> records``.

    Lets us recover species that CBRO files under a different genus than eBird
    (a genus lump/split, e.g. CBRO ``Aburria jacutinga`` vs eBird ``Pipile
    jacutinga``) but where the epithet and family still agree.
    """
    by_ef: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    for sci_key, rec in ebird_index.items():
        parts = sci_key.split()
        if len(parts) < 2:
            continue
        family = str(rec.get("familySciName") or "").strip().lower()
        if not family:
            continue
        by_ef[(parts[1], family)].append((sci_key, rec))
    return by_ef


def _fallback_lookup(
    row: dict[str, object],
    ef_index: dict[tuple[str, str], list[tuple[str, dict]]],
) -> dict | None:
    """Resolve a CBRO row by (epithet, family) in a *different* genus.

    Returns the eBird record only when the match is unambiguous (exactly one
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
    ebird_index: dict[str, dict],
) -> tuple[list[dict[str, object]], int]:
    """Add eBird columns to each CBRO record. Returns (rows, n_matched).

    Two-pass merge: an exact match on normalized scientific name first, then a
    conservative fallback on ``(epithet, family)`` in a different genus to
    recover genus lumps/splits. ``ebird_match_method`` records which pass won.

    Columns added:
        english_name_ebird   eBird comName (empty if no match)
        ebird_species_code   eBird speciesCode (empty if no match)
        ebird_matched        True/False -- matched by either pass
        ebird_match_method   "binomial" | "epithet_family" | "unmatched"
        name_disputed        True when there is a match but the English name
                             differs from the CBRO name (source-divergence
                             candidate)
    """
    ef_index = _epithet_family_index(ebird_index)
    enriched: list[dict[str, object]] = []
    matched = 0

    for row in cbro_rows:
        sci_key = _normalize_sci(str(row["scientific_name"]))
        eb = ebird_index.get(sci_key)
        method = "binomial"
        if eb is None:
            eb = _fallback_lookup(row, ef_index)
            method = "epithet_family"

        if eb is not None:
            matched += 1
            en_ebird = " ".join(str(eb.get("comName", "")).split())
            cbro_en = str(row.get("english_name_cbro", "")).strip()
            disputed = bool(en_ebird) and (
                en_ebird.lower() != cbro_en.lower()
            )
            row = {
                **row,
                "english_name_ebird": en_ebird,
                "ebird_species_code": eb.get("speciesCode", ""),
                "ebird_matched": True,
                "ebird_match_method": method,
                "name_disputed": disputed,
            }
        else:
            row = {
                **row,
                "english_name_ebird": "",
                "ebird_species_code": "",
                "ebird_matched": False,
                "ebird_match_method": "unmatched",
                "name_disputed": False,  # no match -> no names to compare
            }
        enriched.append(row)

    return enriched, matched


def get_token(explicit: str | None = None) -> str:
    """Resolve the eBird token: explicit argument > .env / environment variable.

    Loads a local ``.env`` file (if present) before reading the environment, so
    ``EBIRD_API_TOKEN`` defined there is picked up automatically. An explicit
    argument always wins over the environment.
    """
    if explicit:
        return explicit

    # Load .env if available; harmless no-op when the file or package is absent.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    token = os.environ.get(ENV_TOKEN)
    if not token:
        raise RuntimeError(
            f"eBird token missing. Set {ENV_TOKEN} in a .env file or the "
            f"environment, or pass --token. Generate one at "
            f"https://ebird.org/api/keygen"
        )
    return token


def read_cbro_csv(path: Path) -> list[dict[str, object]]:
    """Read the CSV produced by the ``parse`` command into a list of dicts."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))
