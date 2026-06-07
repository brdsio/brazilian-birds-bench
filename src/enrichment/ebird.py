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
from pathlib import Path

import requests

EBIRD_TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird"
ENV_TOKEN = "EBIRD_API_TOKEN"


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


def enrich_rows(
    cbro_rows: list[dict[str, object]],
    ebird_index: dict[str, dict],
) -> tuple[list[dict[str, object]], int]:
    """Add eBird columns to each CBRO record. Returns (rows, n_matched).

    Columns added:
        english_name_ebird   eBird comName (empty if no match)
        ebird_species_code   eBird speciesCode (empty if no match)
        ebird_matched        True/False -- matched by scientific name
        name_disputed        True when there is a match but the English name
                             differs from the CBRO name (source-divergence
                             candidate)
    """
    enriched: list[dict[str, object]] = []
    matched = 0

    for row in cbro_rows:
        sci_key = _normalize_sci(str(row["scientific_name"]))
        eb = ebird_index.get(sci_key)

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
                "name_disputed": disputed,
            }
        else:
            row = {
                **row,
                "english_name_ebird": "",
                "ebird_species_code": "",
                "ebird_matched": False,
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
