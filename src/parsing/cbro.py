"""Parse the official CBRO spreadsheet (2021 release) into clean records.

Reads the "Lista Primária" sheet, filters down to species level, and returns a
list of CSV-ready dicts -- including taxonomy (order/family/genus) and the
Status field already decomposed into structured columns (see :mod:`.status`).

Official source (Zenodo):
    Pacheco, J. F. et al. (2021). Annotated checklist of the birds of Brazil
    by the Brazilian Ornithological Records Committee -- second edition.
    https://doi.org/10.5281/zenodo.5138368
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import openpyxl

from .status import parse_status

SHEET_NAME = "Lista Primária"
SPECIES_CATEGORY = "Espécie"

# Column names in the spreadsheet. Centralized here so that a layout change in
# a future release can be fixed in a single place.
COL_CBRO_ID = "#CBRO"
COL_CATEGORY = "Categoria"
COL_SCI_NAME = "Nome do táxon (sem autoria)"
COL_ORDER = "Ordem"
COL_FAMILY = "Família"
COL_GENUS = "Gênero"
COL_SPECIES_EPITHET = "Espécie"
COL_PT_NAME = "Nome em Português"
COL_EN_NAME = "English Name"
COL_STATUS = "Status"

# Column order in the output CSV. The taxonomic data and decomposed status feed
# directly into the taxonomic-distance and long-tail analyses.
OUTPUT_FIELDS = [
    "cbro_id",
    "scientific_name",
    "genus",
    "species_epithet",
    "family",
    "order",
    "portuguese_name",
    "english_name_cbro",
    "occurrence",
    "endemic_brazil",
    "extinct",
    "introduced",
    "status_uncertain",
    "origin_directions",
    "status_raw",
]


def normalize_text(value: object) -> str:
    """Coerce to str, apply NFC, and collapse whitespace. '' for empty/None."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return " ".join(text.split())


def _build_header_index(header_row: tuple) -> dict[str, int]:
    header = [normalize_text(c) for c in header_row]
    required = [
        COL_CBRO_ID, COL_CATEGORY, COL_SCI_NAME, COL_ORDER, COL_FAMILY,
        COL_GENUS, COL_SPECIES_EPITHET, COL_PT_NAME, COL_EN_NAME, COL_STATUS,
    ]
    index: dict[str, int] = {}
    for name in required:
        if name not in header:
            raise KeyError(
                f"Expected column not found: {name!r}. Header: {header}"
            )
        index[name] = header.index(name)
    return index


def parse_cbro(xlsx_path: Path) -> list[dict[str, object]]:
    """Read the CBRO spreadsheet and return a list of records (one per species)."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise KeyError(
            f"Sheet {SHEET_NAME!r} not found. Sheets: {wb.sheetnames}"
        )
    ws = wb[SHEET_NAME]

    rows = ws.iter_rows(values_only=True)
    idx = _build_header_index(next(rows))

    records: list[dict[str, object]] = []
    seen_sci: set[str] = set()

    for raw in rows:
        if normalize_text(raw[idx[COL_CATEGORY]]) != SPECIES_CATEGORY:
            continue  # skip order/family/genus/subspecies rows

        sci = normalize_text(raw[idx[COL_SCI_NAME]])
        pt = normalize_text(raw[idx[COL_PT_NAME]])
        en = normalize_text(raw[idx[COL_EN_NAME]])
        if not (sci and pt and en):
            continue  # safety net: a species with no names is dropped

        if sci in seen_sci:
            print(f"Warning: duplicate scientific name skipped: {sci}",
                  file=sys.stderr)
            continue
        seen_sci.add(sci)

        status = parse_status(normalize_text(raw[idx[COL_STATUS]]))

        records.append({
            "cbro_id": normalize_text(raw[idx[COL_CBRO_ID]]),
            "scientific_name": sci,
            "genus": normalize_text(raw[idx[COL_GENUS]]),
            "species_epithet": normalize_text(raw[idx[COL_SPECIES_EPITHET]]),
            "family": normalize_text(raw[idx[COL_FAMILY]]),
            "order": normalize_text(raw[idx[COL_ORDER]]),
            "portuguese_name": pt,
            "english_name_cbro": en,
            "occurrence": status.occurrence,
            "endemic_brazil": status.endemic_brazil,
            "extinct": status.extinct,
            "introduced": status.introduced,
            "status_uncertain": status.status_uncertain,
            "origin_directions": status.origin_directions,
            "status_raw": status.status_raw,
        })

    return records
