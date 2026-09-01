"""``bbb`` CLI -- data pipeline and benchmark runner for brazilian-birds-bench.

Subcommands:

    bbb build   Download CBRO + AviList, fetch the eBird taxonomy, merge all
                three authorities by scientific name, and write the final CSV.

    bbb run     Run the benchmark against an LLM via OpenRouter, saving each
                result incrementally. Supports --resume and --dry-run.

    bbb score   Re-apply scoring to an existing results CSV (no LLM calls).

    bbb audit   Sample errors for manual review.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import random
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import click

from .enrichment.avilist import (
    AVILIST_FIELDS,
    load_avilist_index,
)
from .enrichment.avilist import (
    enrich_rows as enrich_rows_avilist,
)
from .enrichment.ebird import (
    EBIRD_FIELDS,
    fetch_ebird_taxonomy,
    get_token,
)
from .enrichment.ebird import (
    enrich_rows as enrich_rows_ebird,
)
from .parsing.cbro import OUTPUT_FIELDS, parse_cbro

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

AUDIT_COLUMNS = [
    "portuguese_name", "english_name_cbro", "model_response",
    "exact_match", "acceptable_match", "match_source",
    "error_type", "taxonomic_distance", "human_label",
]


def _model_slug(model: str) -> str:
    return model.replace("/", "--")


def _load_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(rows: list[dict], fieldnames: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _run_metadata(dataset_path: Path, config_path: Path) -> dict[str, str]:
    from .runner import SYSTEM_PROMPT, USER_TEMPLATE

    prompt = json.dumps(
        {"system": SYSTEM_PROMPT, "user_template": USER_TEMPLATE},
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "run_started_at_utc": datetime.now(UTC).isoformat(),
        "dataset_sha256": _sha256(dataset_path),
        "config_sha256": _sha256(config_path) if config_path.exists() else "",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "requests_version": version("requests"),
    }


def _write_manifest(
    output_path: Path, metadata: dict[str, str], **settings: object,
) -> None:
    manifest = {**metadata, **settings}
    path = output_path.with_suffix(".manifest.json")
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _index_resume_rows(
    rows: list[dict[str, str]],
    model: str,
    benchmark_mode: str,
    reasoning_config: dict[str, object] | None,
) -> dict[str, dict[str, str]]:
    """Validate and index prior output by stable species identity."""
    indexed: dict[str, dict[str, str]] = {}
    expected_reasoning = json.dumps(reasoning_config) if reasoning_config else ""
    for row in rows:
        row_id = row.get("cbro_id", "")
        if not row_id:
            raise click.ClickException("Resume file contains a row without cbro_id.")
        if row_id in indexed:
            raise click.ClickException(f"Duplicate cbro_id in resume file: {row_id}")
        if row.get("model") and row["model"] != model:
            raise click.ClickException(
                f"Resume model mismatch: {row['model']!r} != {model!r}"
            )
        if row.get("benchmark_mode", "") != benchmark_mode:
            raise click.ClickException(
                "Resume benchmark mode differs from the requested mode."
            )
        if row.get("reasoning_config", "") != expected_reasoning:
            raise click.ClickException(
                "Resume reasoning configuration differs from the requested config."
            )
        indexed[row_id] = row
    return indexed


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
    av_fallback = sum(
        1 for r in records if r["avilist_match_method"] == "epithet_family"
    )
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
    "--max-tokens", type=int, default=None,
    help="Maximum tokens in the LLM response. Defaults to prompt.max_tokens "
         "from the config file (falls back to 1024).",
)
@click.option(
    "--temperature", type=float, default=0.0, show_default=True,
    help="Sampling temperature (0 = deterministic).",
)
@click.option(
    "--reasoning", "reasoning_effort",
    type=click.Choice(["none", "low", "medium", "high"]),
    default="none", show_default=True,
    help="Reasoning effort level sent to the model (legacy; prefer --benchmark-mode).",
)
@click.option(
    "--benchmark-mode", "benchmark_mode",
    type=click.Choice(["no_reasoning", "reasoning"]),
    default=None,
    help="Benchmark mode. no_reasoning omits reasoning; reasoning uses "
         "per-model config from benchmark_config.json.",
)
@click.option(
    "--config", "config_path", type=click.Path(path_type=Path),
    default="benchmark_config.json", show_default=True,
    help="Path to benchmark configuration file.",
)
@click.option(
    "--provider", default=None,
    help="Pin an OpenRouter provider slug for reproducible routing.",
)
@click.option(
    "--allow-provider-fallback/--no-provider-fallback", default=False,
    help="Allow OpenRouter to fail over when --provider is set.",
)
@click.option(
    "--resume", is_flag=True, default=False,
    help="Resume an interrupted run: skip completed rows, retry errors.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Estimate token count and cost without making API calls.",
)
def run(model: str, dataset_path: Path, output_path: Path | None,
        token: str | None, max_tokens: int | None, temperature: float,
        reasoning_effort: str, benchmark_mode: str | None,
        config_path: Path, provider: str | None, allow_provider_fallback: bool,
        resume: bool, dry_run: bool) -> None:
    """Run the benchmark against an LLM via OpenRouter."""
    from .runner import ESTIMATED_PROMPT_TOKENS, get_openrouter_token, process_row
    from .scoring import build_name_index, score_row

    # --- Load benchmark config once (used for max_tokens and reasoning) ---
    bench_config: dict[str, object] = {}
    if Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            bench_config = json.load(f)

    # --- Resolve max_tokens: explicit flag wins, else config, else 1024 ---
    if max_tokens is None:
        max_tokens = bench_config.get("prompt", {}).get("max_tokens", 1024)

    # --- Resolve reasoning configuration ---
    if benchmark_mode is not None and reasoning_effort != "none":
        raise click.ClickException(
            "--benchmark-mode and --reasoning are mutually exclusive."
        )

    reasoning_config: dict[str, object] | None = None

    if benchmark_mode == "no_reasoning":
        # Explicitly request reasoning OFF. If a model rejects this setting the
        # request is recorded as an API error; the protocol is never changed.
        reasoning_config = {"effort": "none"}
    elif benchmark_mode == "reasoning":
        model_reasoning = bench_config.get("reasoning_by_model", {}).get(model)
        if model_reasoning is None:
            available = list(bench_config.get("reasoning_by_model", {}).keys())
            raise click.ClickException(
                f"Model {model!r} not found in reasoning_by_model in {config_path}. "
                f"Available: {available}"
            )
        reasoning_config = {
            k: v for k, v in model_reasoning.items() if k != "exclude"
        }
    elif reasoning_effort != "none":
        reasoning_config = {"effort": reasoning_effort}

    effective_mode = benchmark_mode or ""
    provider_config = None
    if provider:
        provider_config = {
            "order": [provider],
            "allow_fallbacks": allow_provider_fallback,
        }

    # --- Output path ---
    if output_path is None:
        slug = _model_slug(model)
        if benchmark_mode:
            mode_tag = f"_{benchmark_mode}"
        elif reasoning_effort != "none":
            mode_tag = f"_reasoning-{reasoning_effort}"
        else:
            mode_tag = ""
        output_path = Path(f"results/{slug}{mode_tag}.csv")

    dataset_raw = _load_csv(dataset_path)
    dataset = [
        r for r in dataset_raw
        if r.get("ebird_matched") != "False" and r.get("avilist_matched") != "False"
    ]
    skipped = len(dataset_raw) - len(dataset)
    total = len(dataset)

    click.echo(
        f"Model:          {model}\n"
        f"Benchmark mode: {benchmark_mode or 'N/A'}\n"
        f"Reasoning cfg:  {reasoning_config}\n"
        f"Provider cfg:   {provider_config}\n"
        f"Dataset:        {dataset_path} ({total} species"
        f"{f', {skipped} skipped without eBird/AviList match' if skipped else ''})\n"
        f"Output:         {output_path}\n"
        f"Temperature:    {temperature}\n"
        f"Max tokens:     {max_tokens}",
        err=True,
    )

    if dry_run:
        est_prompt = total * ESTIMATED_PROMPT_TOKENS
        est_completion = total * 10
        click.echo(
            f"\n-- Dry run estimate --\n"
            f"  Species:            {total}\n"
            f"  Est. prompt tokens: ~{est_prompt:,}\n"
            f"  Est. completion:    ~{est_completion:,}\n"
            f"  Est. total tokens:  ~{est_prompt + est_completion:,}\n"
            f"\n  Check model pricing at https://openrouter.ai/models/{model}",
            err=True,
        )
        return

    resolved_token = get_openrouter_token(token)
    name_index = build_name_index(dataset)
    run_meta = _run_metadata(dataset_path, config_path)
    run_meta["requested_provider"] = provider or ""
    run_meta["provider_fallback_allowed"] = str(
        bool(provider and allow_provider_fallback)
    )
    run_settings = {
        "requested_model": model,
        "benchmark_mode": effective_mode,
        "reasoning_config": reasoning_config,
        "provider_config": provider_config,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "dataset": str(dataset_path),
    }

    def _score(row: dict) -> dict:
        return score_row(row, name_index)

    # --- Resume logic ---
    existing_by_id: dict[str, dict[str, str]] = {}

    if resume and output_path.exists():
        manifest_path = output_path.with_suffix(".manifest.json")
        if manifest_path.exists():
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key in (
                "dataset_sha256", "config_sha256", "prompt_sha256", "git_commit"
            ):
                if previous_manifest.get(key) != run_meta.get(key):
                    raise click.ClickException(
                        f"Resume metadata mismatch for {key}: refusing mixed run."
                    )
            for key, expected in run_settings.items():
                if previous_manifest.get(key) != expected:
                    raise click.ClickException(
                        f"Resume setting mismatch for {key}: refusing mixed run."
                    )
        existing_by_id = _index_resume_rows(
            _load_csv(output_path), model, effective_mode, reasoning_config,
        )
        n_retry = sum(
            row.get("finish_reason") == "error" for row in existing_by_id.values()
        )
        n_complete = len(existing_by_id) - n_retry
        click.echo(
            f"Resuming: {n_complete} completed, {n_retry} to retry, "
            f"{total - len(existing_by_id)} new rows.",
            err=True,
        )

    _write_manifest(output_path, run_meta, **run_settings)

    # --- Determine fieldnames from a dry score of the first row ---
    dummy_result = {**dataset[0], "model": model, **run_meta, "model_response": "",
                    "finish_reason": "", "truncated": False,
                    "reasoning_config": "", "effective_reasoning_config": "",
                    "benchmark_mode": "", "resolved_model": "",
                    "generation_id": "", "request_id": "", "provider": "",
                    "response_created": "", "requested_at_utc": "",
                    "latency_ms": 0,
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "error": ""}
    fieldnames = list(score_row(dummy_result, name_index).keys())

    # --- Run loop with incremental save ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_scored: list[dict] = []

    with open(output_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        # Always emit dataset order. Identity is cbro_id, never CSV position.
        for i, row in enumerate(dataset):
            previous = existing_by_id.get(row["cbro_id"])
            if previous is not None and previous.get("finish_reason") != "error":
                scored = score_row(previous, name_index)
            else:
                scored = process_row(
                    row, model, resolved_token,
                    temperature=temperature, max_tokens=max_tokens,
                    reasoning_config=reasoning_config,
                    provider_config=provider_config,
                    benchmark_mode=effective_mode,
                    index=i + 1, total=total,
                    score_fn=_score,
                    run_metadata=run_meta,
                )
            writer.writerow(scored)
            fh.flush()
            all_scored.append(scored)

    _print_run_summary(all_scored, output_path)


def _print_run_summary(scored: list[dict], output_path: Path) -> None:
    total = len(scored)
    if total == 0:
        click.echo("No results.", err=True)
        return

    exact = sum(1 for r in scored if r.get("exact_match") in (True, "True"))
    acceptable = sum(1 for r in scored if r.get("acceptable_match") in (True, "True"))
    truncated = sum(1 for r in scored if r.get("truncated") in (True, "True"))
    errors = sum(1 for r in scored if r.get("finish_reason") == "error")

    click.echo(f"\n{'='*55}", err=True)
    click.echo(f"Results: {total} species -> {output_path}", err=True)
    click.echo(
        f"  Exact match:      {exact}/{total} ({100 * exact / total:.1f}%)",
        err=True,
    )
    click.echo(
        f"  Acceptable match: {acceptable}/{total} "
        f"({100 * acceptable / total:.1f}%)",
        err=True,
    )
    if truncated:
        click.echo(
            f"  Truncated:        {truncated}/{total} ({100*truncated/total:.1f}%) "
            f"[finish_reason=length]",
            err=True,
        )
    if errors:
        click.echo(
            f"  Errors:           {errors}/{total} ({100 * errors / total:.1f}%)",
            err=True,
        )

    # Token / latency stats
    latencies = [
        int(r["latency_ms"]) for r in scored
        if str(r.get("latency_ms", "0")).isdigit() and int(r["latency_ms"]) > 0
    ]
    prompt_tok = sum(int(r.get("prompt_tokens", 0)) for r in scored)
    comp_tok = sum(int(r.get("completion_tokens", 0)) for r in scored)
    total_tok = sum(int(r.get("total_tokens", 0)) for r in scored)

    if latencies:
        latencies.sort()
        avg = sum(latencies) / len(latencies)
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)]
        click.echo(
            f"\n  Latency:  avg {avg:.0f}ms  |  p95 {p95}ms",
            err=True,
        )
    if total_tok:
        click.echo(
            f"  Tokens:   {prompt_tok:,} prompt + {comp_tok:,} completion "
            f"= {total_tok:,} total",
            err=True,
        )

    # Match sources
    source_counts: dict[str, int] = {}
    for r in scored:
        src = r.get("match_source", "")
        if src:
            source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        click.echo("\n  Match sources:", err=True)
        for src, count in sorted(source_counts.items()):
            click.echo(f"    {src}: {count}", err=True)

    # Error types
    error_counts: dict[str, int] = {}
    for r in scored:
        et = r.get("error_type", "")
        if et and et != "correct":
            error_counts[et] = error_counts.get(et, 0) + 1
    if error_counts:
        click.echo("\n  Error types:", err=True)
        for et, count in sorted(error_counts.items()):
            click.echo(f"    {et}: {count}", err=True)

    click.echo(f"{'='*55}", err=True)


# ---------------------------------------------------------------------------
# bbb score
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--input", "input_path", required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Results CSV from 'bbb run'.",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default=None,
    help="Output CSV. Defaults to overwriting the input file.",
)
@click.option(
    "--dataset", "dataset_path", type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_DATASET, show_default=True,
    help="Complete reference dataset used to build the taxonomy index.",
)
def score(input_path: Path, output_path: Path | None, dataset_path: Path) -> None:
    """Re-apply scoring to an existing results CSV (no LLM calls)."""
    from .scoring import build_name_index, score_row

    if output_path is None:
        output_path = input_path

    rows = _load_csv(input_path)
    dataset = [
        row for row in _load_csv(dataset_path)
        if row.get("ebird_matched") != "False"
        and row.get("avilist_matched") != "False"
    ]
    name_index = build_name_index(dataset)
    scored = [score_row(row, name_index) for row in rows]

    fieldnames = list(scored[0].keys()) if scored else []
    _write_csv(scored, fieldnames, output_path)

    click.echo(f"Re-scored {len(scored)} rows -> {output_path}", err=True)
    _print_run_summary(scored, output_path)


# ---------------------------------------------------------------------------
# bbb stats
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--input", "input_paths", multiple=True, required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Result CSV; repeat to compare multiple runs.",
)
@click.option(
    "--metric", type=click.Choice(["exact_match", "acceptable_match"]),
    default="acceptable_match", show_default=True,
)
@click.option("--bootstrap-samples", type=int, default=10_000, show_default=True)
@click.option("--seed", type=int, default=42, show_default=True)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path), default=None,
    help="Optional CSV output for estimates and pairwise McNemar tests.",
)
def stats(input_paths: tuple[Path, ...], metric: str, bootstrap_samples: int,
          seed: int, output_path: Path | None) -> None:
    """Report bootstrap confidence intervals and paired McNemar comparisons."""
    from itertools import combinations

    from .statistics import bootstrap_accuracy_ci, mcnemar_exact

    loaded = {path: _load_csv(path) for path in input_paths}
    for path, rows in loaded.items():
        if not rows or "cbro_id" not in rows[0] or metric not in rows[0]:
            raise click.ClickException(
                f"{path} is not a benchmark result CSV with {metric!r}."
            )
    output_rows: list[dict[str, object]] = []
    for path, rows in loaded.items():
        estimate, lo, hi = bootstrap_accuracy_ci(
            rows, metric, samples=bootstrap_samples, seed=seed,
        )
        click.echo(
            f"{path}: {estimate:.2%} (95% bootstrap CI {lo:.2%}–{hi:.2%}; "
            f"n={len(rows)})"
        )
        output_rows.append({
            "analysis": "bootstrap_ci", "left": str(path), "right": "",
            "metric": metric, "n": len(rows), "estimate": estimate,
            "ci_low": lo, "ci_high": hi, "left_only_correct": "",
            "right_only_correct": "", "p_value": "",
        })

    for (left_path, left), (right_path, right) in combinations(loaded.items(), 2):
        result = mcnemar_exact(left, right, metric)
        click.echo(
            f"{left_path} vs {right_path}: McNemar exact p="
            f"{result['p_value']:.6g}, discordant={result['discordant']}, "
            f"n={result['n_paired']}"
        )
        output_rows.append({
            "analysis": "mcnemar_exact", "left": str(left_path),
            "right": str(right_path), "metric": metric,
            "n": result["n_paired"], "estimate": "", "ci_low": "",
            "ci_high": "", "left_only_correct": result["left_only_correct"],
            "right_only_correct": result["right_only_correct"],
            "p_value": result["p_value"],
        })

    if output_path:
        _write_csv(output_rows, list(output_rows[0]), output_path)


# ---------------------------------------------------------------------------
# bbb audit
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--input", "input_path", required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Results CSV from 'bbb run'.",
)
@click.option(
    "--sample", "sample_size", type=int, default=50, show_default=True,
    help="Number of errors to sample.",
)
@click.option(
    "--output", "output_path", type=click.Path(path_type=Path),
    default=None,
    help="Audit CSV. Defaults to audit/<input-stem>_audit.csv.",
)
@click.option(
    "--seed", type=int, default=42, show_default=True,
    help="Random seed for reproducible sampling.",
)
def audit(input_path: Path, sample_size: int,
          output_path: Path | None, seed: int) -> None:
    """Sample errors from a results CSV for manual review."""
    rows = _load_csv(input_path)

    errors = [r for r in rows if r.get("error_type", "correct") != "correct"]
    if not errors:
        click.echo("No errors to audit.", err=True)
        return

    rng = random.Random(seed)
    sampled = rng.sample(errors, min(sample_size, len(errors)))

    if output_path is None:
        output_path = Path(f"audit/{input_path.stem}_audit.csv")

    audit_rows = []
    for r in sampled:
        audit_row = {
            col: r.get(col, "") for col in AUDIT_COLUMNS if col != "human_label"
        }
        audit_row["human_label"] = ""
        audit_rows.append(audit_row)

    _write_csv(audit_rows, AUDIT_COLUMNS, output_path)

    # Breakdown of sampled error types
    type_counts: dict[str, int] = {}
    for r in sampled:
        et = r.get("error_type", "unknown")
        type_counts[et] = type_counts.get(et, 0) + 1

    click.echo(
        f"Sampled {len(sampled)} errors (of {len(errors)} total) -> {output_path}",
        err=True,
    )
    for et, count in sorted(type_counts.items()):
        click.echo(f"  {et}: {count}", err=True)
    click.echo(
        "\nFill the 'human_label' column, then use 'bbb score' to re-apply "
        "scoring after adjusting classifiers.",
        err=True,
    )


if __name__ == "__main__":
    cli()
