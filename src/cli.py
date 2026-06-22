"""``bbb`` CLI -- data pipeline for the brazilian-birds-bench benchmark.

A single command runs the whole pipeline end-to-end:

    bbb   Download CBRO + AviList, fetch the eBird taxonomy, merge all three
          authorities by scientific name, and write one final CSV carrying both
          name_disputed columns.

The command is intentionally thin: all logic lives in :mod:`src.parsing` and
:mod:`src.enrichment`. Here we only wire arguments to calls.
"""

from __future__ import annotations

import csv
from pathlib import Path

import click

from .parsing.cbro import OUTPUT_FIELDS, parse_cbro
from .enrichment.ebird import (
    EBIRD_FIELDS,
    enrich_rows as enrich_rows_ebird,
    fetch_ebird_taxonomy,
    get_token,
)
from .enrichment.avilist import (
    AVILIST_FIELDS,
    enrich_rows as enrich_rows_avilist,
    load_avilist_index,
)

ZENODO_URL = (
    "https://zenodo.org/record/5138368/files/"
    "2021.07.26%20CBRO%202021%20Zenodo%20Release.xlsx?download=1"
)

# Direct download for the AviList Short spreadsheet (v2025, 11-Jun release).
AVILIST_URL = (
    "https://www.avilist.org/wp-content/uploads/2025/06/"
    "AviList-v2025-11Jun-short.xlsx"
)

DEFAULT_CBRO_FILE = "data_raw/cbro_2021.xlsx"
DEFAULT_AVILIST_FILE = "data_raw/avilist_v2025_short.xlsx"
DEFAULT_OUTPUT = "src/data/benchmark_dataset.csv"


def _write_csv(rows: list[dict], fieldnames: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _download(url: str, dest: Path) -> None:
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    click.echo(f"Downloading {url} ...", err=True)
    with requests.get(url, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    click.echo(f"Saved to {dest}", err=True)


@click.command()
@click.option(
    "--cbro-file", "cbro_path", type=click.Path(path_type=Path),
    default=DEFAULT_CBRO_FILE, show_default=True,
    help="Local CBRO .xlsx (downloaded if missing, unless --no-download).",
)
@click.option(
    "--avilist-file", "avilist_path", type=click.Path(path_type=Path),
    default=DEFAULT_AVILIST_FILE, show_default=True,
    help="Local AviList .xlsx (downloaded if missing, unless --no-download).",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default=DEFAULT_OUTPUT, show_default=True,
    help="Final CSV with all three authorities and both name_disputed columns.",
)
@click.option(
    "--token", default=None,
    help="eBird API token. Defaults to the EBIRD_API_TOKEN environment variable.",
)
@click.option(
    "--locale", default="en", show_default=True,
    help="Locale for the eBird common name (en = English).",
)
@click.option(
    "--download/--no-download", default=True, show_default=True,
    help="Download CBRO/AviList sources when the local file is missing.",
)
@click.version_option()
def cli(cbro_path: Path, avilist_path: Path, output_path: Path,
        token: str | None, locale: str, download: bool) -> None:
    """Build the brazilian-birds-bench dataset in one shot.

    Downloads any missing source (CBRO from Zenodo, AviList from avilist.org),
    fetches the eBird taxonomy, and merges all three authorities by scientific
    name into one CSV carrying both ``name_disputed`` (eBird vs CBRO) and
    ``name_disputed_avilist`` (AviList vs CBRO). Local source files, if present,
    are reused as a cache; pass ``--no-download`` to require them instead.
    Needs an eBird token: set EBIRD_API_TOKEN in a .env file or pass --token.
    """
    # 1. CBRO -> base records (offline once the .xlsx is local).
    if download and not cbro_path.exists():
        _download(ZENODO_URL, cbro_path)
    if not cbro_path.exists():
        raise click.ClickException(
            f"CBRO file not found: {cbro_path}. Drop --no-download or set --cbro-file."
        )
    records = parse_cbro(cbro_path)

    # 2. eBird -> english_name_ebird + name_disputed (online; needs a token).
    resolved_token = get_token(token)
    ebird_index = fetch_ebird_taxonomy(resolved_token, locale=locale)
    records, ebird_matched = enrich_rows_ebird(records, ebird_index)

    # 3. AviList -> english_name_avilist + name_disputed_avilist (offline once local).
    if download and not avilist_path.exists():
        _download(AVILIST_URL, avilist_path)
    if not avilist_path.exists():
        raise click.ClickException(
            f"AviList file not found: {avilist_path}. Drop --no-download or set "
            f"--avilist-file."
        )
    avilist_index = load_avilist_index(avilist_path)
    records, avilist_matched = enrich_rows_avilist(records, avilist_index)

    # 4. One final CSV with every column.
    fields = OUTPUT_FIELDS + EBIRD_FIELDS + AVILIST_FIELDS
    _write_csv(records, fields, output_path)

    total = len(records)
    eb_fallback = sum(1 for r in records if r["ebird_match_method"] == "epithet_family")
    av_fallback = sum(1 for r in records if r["avilist_match_method"] == "epithet_family")
    eb_disputed = sum(1 for r in records if r["name_disputed"])
    av_disputed = sum(1 for r in records if r["name_disputed_avilist"])
    click.echo(
        f"OK: {total} species -> {output_path}\n"
        f"    eBird:   {ebird_matched} matched ({eb_fallback} via epithet+family) | "
        f"{total - ebird_matched} unmatched | {eb_disputed} name_disputed\n"
        f"    AviList: {avilist_matched} matched ({av_fallback} via epithet+family) | "
        f"{total - avilist_matched} unmatched | {av_disputed} name_disputed_avilist",
        err=True,
    )


if __name__ == "__main__":
    cli()
