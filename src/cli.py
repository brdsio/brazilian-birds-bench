"""``bbb`` CLI -- data pipeline for the brazilian-birds-bench benchmark.

Subcommands:
    bbb parse           Read the CBRO spreadsheet and produce the species CSV.
    bbb enrich          Add English names from eBird (API) to the species CSV.
    bbb enrich-avilist  Add English names from AviList (local xlsx) to the CSV.

The group is intentionally thin: all logic lives in
:mod:`src.parsing` and :mod:`src.enrichment`.
Here we only wire arguments to calls.
"""

from __future__ import annotations

import csv
from pathlib import Path

import click

from .parsing.cbro import OUTPUT_FIELDS, parse_cbro
from .enrichment.ebird import (
    enrich_rows as enrich_rows_ebird,
    fetch_ebird_taxonomy,
    get_token,
    read_cbro_csv,
)
from .enrichment.avilist import (
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

DEFAULT_SPECIES_CSV = "src/data/cbro_species.csv"
DEFAULT_AVILIST_FILE = "data_raw/avilist_v2025_short.xlsx"


def _write_csv(rows: list[dict], fieldnames: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@click.group()
@click.version_option()
def cli() -> None:
    """brazilian-birds-bench -- data pipeline for the bird-name benchmark."""


@cli.command()
@click.option(
    "--input", "input_path", type=click.Path(path_type=Path),
    default="data_raw/cbro_2021.xlsx", show_default=True,
    help="Path to the CBRO .xlsx file.",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default=DEFAULT_SPECIES_CSV, show_default=True,
    help="Output CSV with the species.",
)
@click.option(
    "--download", is_flag=True,
    help="Download the spreadsheet from Zenodo to --input before parsing.",
)
def parse(input_path: Path, output_path: Path, download: bool) -> None:
    """Read the CBRO spreadsheet and produce the species CSV (decomposed status)."""
    if download:
        _download(ZENODO_URL, input_path)

    if not input_path.exists():
        raise click.ClickException(
            f"File not found: {input_path}. Use --download or set --input."
        )

    records = parse_cbro(input_path)
    _write_csv(records, OUTPUT_FIELDS, output_path)

    endemic = sum(1 for r in records if r["endemic_brazil"])
    genera = len({r["genus"] for r in records})
    families = len({r["family"] for r in records})
    click.echo(
        f"OK: {len(records)} species -> {output_path}\n"
        f"    {endemic} endemic | {genera} genera | {families} families",
        err=True,
    )


@cli.command()
@click.option(
    "--input", "input_path", type=click.Path(path_type=Path),
    default=DEFAULT_SPECIES_CSV, show_default=True,
    help="Species CSV produced by 'bbb parse'.",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default="src/data/cbro_species_ebird.csv",
    show_default=True, help="Output CSV enriched with eBird.",
)
@click.option(
    "--token", default=None,
    help="eBird API token. Defaults to the EBIRD_API_TOKEN environment variable.",
)
@click.option(
    "--locale", default="en", show_default=True,
    help="Locale for the eBird common name (en = English).",
)
def enrich(input_path: Path, output_path: Path,
           token: str | None, locale: str) -> None:
    """Add English names from eBird to the species CSV, by scientific name."""
    if not input_path.exists():
        raise click.ClickException(
            f"Input CSV not found: {input_path}. Run 'bbb parse' first."
        )

    resolved_token = get_token(token)
    cbro_rows = read_cbro_csv(input_path)
    ebird_index = fetch_ebird_taxonomy(resolved_token, locale=locale)
    enriched, matched = enrich_rows_ebird(cbro_rows, ebird_index)

    new_fields = OUTPUT_FIELDS + [
        "english_name_ebird", "ebird_species_code",
        "ebird_matched", "name_disputed",
    ]
    _write_csv(enriched, new_fields, output_path)

    total = len(enriched)
    disputed = sum(1 for r in enriched if r["name_disputed"])
    unmatched = total - matched
    click.echo(
        f"OK: {total} species -> {output_path}\n"
        f"    {matched} eBird-matched | {unmatched} unmatched | "
        f"{disputed} with divergent English name (name_disputed)",
        err=True,
    )


@cli.command(name="enrich-avilist")
@click.option(
    "--input", "input_path", type=click.Path(path_type=Path),
    default=DEFAULT_SPECIES_CSV, show_default=True,
    help="Species CSV produced by 'bbb parse' (or a previously enriched CSV).",
)
@click.option(
    "--avilist-file", "avilist_path", type=click.Path(path_type=Path),
    default=DEFAULT_AVILIST_FILE, show_default=True,
    help="Path to the AviList .xlsx (Short or Extended), from avilist.org.",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default="src/data/cbro_species_avilist.csv",
    show_default=True, help="Output CSV enriched with AviList.",
)
@click.option(
    "--download", is_flag=True,
    help="Download the AviList Short spreadsheet to --avilist-file first.",
)
def enrich_avilist(input_path: Path, avilist_path: Path,
                   output_path: Path, download: bool) -> None:
    """Add English names from AviList (local xlsx) to the species CSV.

    AviList is the unified IOC/Clements/BirdLife checklist. Use --download to
    fetch the Short spreadsheet automatically, or pass an existing copy with
    --avilist-file. This command runs offline once the file is present; chaining
    it on top of the eBird output lets you triangulate three authorities (CBRO,
    eBird, AviList).
    """
    if not input_path.exists():
        raise click.ClickException(
            f"Input CSV not found: {input_path}. Run 'bbb parse' first."
        )
    if download:
        _download(AVILIST_URL, avilist_path)
    if not avilist_path.exists():
        raise click.ClickException(
            f"AviList file not found: {avilist_path}. Use --download, or grab "
            f"it from https://www.avilist.org/checklist/v2025/"
        )

    cbro_rows = read_cbro_csv(input_path)
    avilist_index = load_avilist_index(avilist_path)
    enriched, matched = enrich_rows_avilist(cbro_rows, avilist_index)

    # Preserve any columns already present (e.g. eBird) and append AviList ones.
    base_fields = list(cbro_rows[0].keys()) if cbro_rows else OUTPUT_FIELDS
    avilist_fields = [
        "english_name_avilist", "avilist_matched", "name_disputed_avilist",
    ]
    new_fields = base_fields + [f for f in avilist_fields if f not in base_fields]
    _write_csv(enriched, new_fields, output_path)

    total = len(enriched)
    disputed = sum(1 for r in enriched if r["name_disputed_avilist"])
    unmatched = total - matched
    click.echo(
        f"OK: {total} species -> {output_path}\n"
        f"    {matched} AviList-matched | {unmatched} unmatched | "
        f"{disputed} with divergent English name (name_disputed_avilist)",
        err=True,
    )


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


if __name__ == "__main__":
    cli()
