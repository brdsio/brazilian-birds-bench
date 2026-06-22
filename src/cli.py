"""``bbb`` CLI -- data pipeline and benchmark runner for brazilian-birds-bench.

Subcommands:

    bbb build   Download CBRO + AviList, fetch the eBird taxonomy, merge all
                three authorities by scientific name, and write the final CSV.

    bbb run     Run the benchmark: send every Portuguese name to an LLM via
                OpenRouter, score the responses, and write a results CSV.

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

AVILIST_URL = (
    "https://www.avilist.org/wp-content/uploads/2025/06/"
    "AviList-v2025-11Jun-short.xlsx"
)

DEFAULT_CBRO_FILE = "data_raw/cbro_2021.xlsx"
DEFAULT_AVILIST_FILE = "data_raw/avilist_v2025_short.xlsx"
DEFAULT_DATASET = "src/data/benchmark_dataset.csv"


def _model_slug(model: str) -> str:
    """Turn a model ID like 'google/gemini-2.0-flash' into a filename-safe slug."""
    return model.replace("/", "--")


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


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option()
def cli() -> None:
    """brazilian-birds-bench: benchmark LLM knowledge on Brazilian bird names."""


# ---------------------------------------------------------------------------
# bbb build
# ---------------------------------------------------------------------------

@cli.command()
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
    default=DEFAULT_DATASET, show_default=True,
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
def build(cbro_path: Path, avilist_path: Path, output_path: Path,
          token: str | None, locale: str, download: bool) -> None:
    """Build the benchmark dataset from CBRO, eBird, and AviList."""
    if download and not cbro_path.exists():
        _download(ZENODO_URL, cbro_path)
    if not cbro_path.exists():
        raise click.ClickException(
            f"CBRO file not found: {cbro_path}. Drop --no-download or set --cbro-file."
        )
    records = parse_cbro(cbro_path)

    resolved_token = get_token(token)
    ebird_index = fetch_ebird_taxonomy(resolved_token, locale=locale)
    records, ebird_matched = enrich_rows_ebird(records, ebird_index)

    if download and not avilist_path.exists():
        _download(AVILIST_URL, avilist_path)
    if not avilist_path.exists():
        raise click.ClickException(
            f"AviList file not found: {avilist_path}. Drop --no-download or set "
            f"--avilist-file."
        )
    avilist_index = load_avilist_index(avilist_path)
    records, avilist_matched = enrich_rows_avilist(records, avilist_index)

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


# ---------------------------------------------------------------------------
# bbb run
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--model", required=True,
    help="OpenRouter model ID (e.g. google/gemini-2.0-flash).",
)
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_DATASET, show_default=True,
    help="Input dataset CSV (the output of 'bbb build').",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default=None,
    help="Results CSV path. Defaults to results/<model-slug>.csv.",
)
@click.option(
    "--token", default=None,
    help="OpenRouter API key. Defaults to the OPENROUTER_API_KEY env var.",
)
@click.option(
    "--max-tokens", type=int, default=1024, show_default=True,
    help="Maximum tokens in the LLM response.",
)
@click.option(
    "--temperature", type=float, default=0.0, show_default=True,
    help="Sampling temperature (0 = deterministic).",
)
def run(model: str, dataset_path: Path, output_path: Path | None,
        token: str | None, max_tokens: int, temperature: float) -> None:
    """Run the benchmark against an LLM via OpenRouter."""
    from .runner import get_openrouter_token, run_benchmark
    from .scoring import score_results

    if output_path is None:
        output_path = Path(f"results/{_model_slug(model)}.csv")

    resolved_token = get_openrouter_token(token)

    click.echo(
        f"Model:       {model}\n"
        f"Dataset:     {dataset_path}\n"
        f"Output:      {output_path}\n"
        f"Temperature: {temperature}\n"
        f"Max tokens:  {max_tokens}",
        err=True,
    )

    results = run_benchmark(
        dataset_path, model, resolved_token,
        temperature=temperature, max_tokens=max_tokens,
    )
    scored = score_results(results)

    fieldnames = list(scored[0].keys()) if scored else []
    _write_csv(scored, fieldnames, output_path)

    _print_run_summary(scored, output_path)


def _print_run_summary(scored: list[dict], output_path: Path) -> None:
    total = len(scored)
    if total == 0:
        click.echo("No results.", err=True)
        return

    exact = sum(1 for r in scored if r["exact_match"])
    acceptable = sum(1 for r in scored if r["acceptable_match"])
    truncated = sum(1 for r in scored if r["truncated"])
    errors = sum(1 for r in scored if r["finish_reason"] == "error")

    click.echo(f"\n{'='*50}", err=True)
    click.echo(f"Results: {total} species -> {output_path}", err=True)
    click.echo(f"  Exact match:      {exact}/{total} ({100*exact/total:.1f}%)", err=True)
    click.echo(f"  Acceptable match: {acceptable}/{total} ({100*acceptable/total:.1f}%)", err=True)
    if truncated:
        click.echo(
            f"  Truncated:        {truncated}/{total} ({100*truncated/total:.1f}%) "
            f"[finish_reason=length]",
            err=True,
        )
    if errors:
        click.echo(f"  Errors:           {errors}/{total} ({100*errors/total:.1f}%)", err=True)

    source_counts: dict[str, int] = {}
    for r in scored:
        src = r.get("match_source", "")
        if src:
            source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        click.echo("\n  Match sources:", err=True)
        for src, count in sorted(source_counts.items()):
            click.echo(f"    {src}: {count}", err=True)

    error_counts: dict[str, int] = {}
    for r in scored:
        et = r.get("error_type", "")
        if et and et != "correct":
            error_counts[et] = error_counts.get(et, 0) + 1
    if error_counts:
        click.echo("\n  Error types:", err=True)
        for et, count in sorted(error_counts.items()):
            click.echo(f"    {et}: {count}", err=True)

    click.echo(f"{'='*50}", err=True)



if __name__ == "__main__":
    cli()
