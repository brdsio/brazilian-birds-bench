# brazilian-birds-bench

A benchmark of large language model knowledge on Brazilian bird names.

The task is deliberately narrow: given the Brazilian Portuguese common name of a
bird, return its English common name. It is a zero-shot, single-turn probe of
what a model *already knows* — no examples, no retrieval, no chain-of-thought
coaxing. The repository contains everything needed to (1) build the reference
dataset from authoritative checklists and (2) run, score, and audit any model
available through OpenRouter against it.

## How it works

1. **`bbb build`** assembles a reference dataset of the ~1,971 bird species
   recorded in Brazil, merging three taxonomic authorities by scientific name.
2. **`bbb run`** asks a model, for each species, to translate the Portuguese
   name to English via OpenRouter, scoring every answer as it goes.
3. **`bbb score`** re-applies the scoring logic to an existing results file
   without making any API calls.
4. **`bbb stats`** reports confidence intervals and paired model comparisons.
5. **`bbb audit`** samples wrong answers into a CSV for manual review.

## Data sources

- **CBRO** — *Comitê Brasileiro de Registros Ornitológicos*, 2021 checklist
  ([Zenodo, DOI 10.5281/zenodo.5138368](https://doi.org/10.5281/zenodo.5138368)).
  The authoritative source of Portuguese and English common names for the
  ~1,971 bird species recorded in Brazil.
- **eBird/Clements** — taxonomy via the
  [eBird API 2.0](https://documenter.getpostman.com/view/664302/S1ENwy59), used
  as a second authority for English names. Divergences between CBRO and eBird
  are flagged rather than resolved.
- **AviList** — the
  [unified global checklist](https://www.avilist.org/checklist/v2025/) (v2025)
  that harmonizes the IOC, Clements, and BirdLife taxonomies, released under
  CC BY 4.0. Used as a third authority. Distributed as an Excel spreadsheet
  (no API), so it is supplied as a local file.

      AviList Core Team. 2025. AviList: The Global Avian Checklist, v2025.
      https://doi.org/10.2173/avilist.v2025

## Installation

```bash
uv sync
uv pip install -e .
```

This installs a single command, `bbb`, with the `build`, `run`, `score`, and
`audit` subcommands. Run `bbb --help` or `bbb <command> --help` for the full
option list.

## 1. Build the dataset (`bbb build`)

### Configure the eBird token

Get an eBird API token at https://ebird.org/api/keygen, then copy the example
env file and fill it in:

```bash
cp .env.example .env
# edit .env and set EBIRD_API_TOKEN=your_token_here
```

The token is loaded automatically from `.env` (no manual `export` needed). You
can also pass it ad hoc with `bbb build --token your_token_here`.

### Run the build

```bash
bbb build
```

`bbb build` runs every stage end-to-end and writes a single
`src/data/benchmark_dataset.csv` with all three authorities and both divergence
columns (`name_disputed` for eBird, `name_disputed_avilist` for AviList).
Specifically it:

1. **Parses the CBRO checklist** → scientific name, taxonomy (order / family /
   genus), Portuguese and English names, and the CBRO status field decomposed
   into structured columns (`occurrence`, `endemic_brazil`, `extinct`,
   `introduced`, `status_uncertain`, `origin_directions`).
2. **Merges eBird/Clements** by scientific name → `english_name_ebird`,
   `ebird_species_code`, `ebird_matched`, `ebird_match_method`, `name_disputed`.
3. **Merges AviList** by scientific name → `english_name_avilist`,
   `avilist_matched`, `avilist_match_method`, `name_disputed_avilist`.

Matching runs in two passes: an exact match on the scientific binomial, then a
conservative fallback on `(epithet, family)` in a different genus that recovers
genus lumps/splits (e.g. CBRO *Aburria jacutinga* ↔ *Pipile jacutinga*). The
`*_match_method` columns record which pass matched each row (`binomial`,
`epithet_family`, or `unmatched`).

It **downloads whatever it needs** — the CBRO spreadsheet from Zenodo and the
AviList spreadsheet from avilist.org — so you never have to place a source file
by hand. Local copies, if present in `data_raw/`, are reused as a cache. Pass
`--no-download` to require local copies and fail if they are missing.

Useful options:

```bash
bbb build --output data/birds.csv      # change the output path
bbb build --no-download                # require local source files, never fetch
bbb build --cbro-file path/to.xlsx     # use a specific CBRO copy
bbb build --avilist-file path/to.xlsx  # use a specific AviList copy
bbb build --locale pt                  # eBird common-name locale (default: en)
```

## 2. Run the benchmark (`bbb run`)

`bbb run` evaluates one model against the dataset through
[OpenRouter](https://openrouter.ai), which exposes an OpenAI-compatible
chat-completions endpoint, so any model on the platform (GPT, Claude, Gemini,
Llama, Mistral, …) is reachable with a single `--model` flag.

Set an OpenRouter API key in `.env` (`OPENROUTER_API_KEY=...`) or pass
`--token`, then:

```bash
bbb run --model anthropic/claude-opus-4.8
```

The prompt is **zero-shot and fixed**: a system message constrains the output to
the English common name only, and the user message contains nothing but the
Portuguese name. Each row is called with `temperature 0` for determinism, scored
immediately, and written incrementally so an interrupted run loses nothing.
Species without an eBird *and* AviList match are skipped. By default results go
to `results/<model-slug>_<mode>.csv`. New runs also write a JSON manifest with
dataset/config/prompt hashes, Git commit, runtime versions, routing policy, and
generation settings. Use `--provider` to pin an OpenRouter provider; fallback
is disabled unless explicitly enabled.

### Reasoning modes

`benchmark_config.json` defines two benchmark modes and per-model reasoning
settings:

- `--benchmark-mode no_reasoning` requests `effort: none`. If a model rejects
  it, the request is recorded as an API error; the protocol is never silently
  changed.
- `--benchmark-mode reasoning` applies each model's entry from
  `reasoning_by_model` in the config (effort level or fixed token budget).

A legacy `--reasoning {none,low,medium,high}` flag is also available for ad-hoc
runs; it is mutually exclusive with `--benchmark-mode`.

### Other options

```bash
bbb run --model openai/gpt-5.5 --dry-run   # estimate token count, no API calls
bbb run --model openai/gpt-5.5 --resume    # skip completed rows, retry errors
bbb run --model openai/gpt-5.5 --max-tokens 2048 --temperature 0.0
bbb run --model openai/gpt-5.5 --output results/custom.csv
```

## 3. Scoring (`bbb score`)

Scoring is applied during `bbb run` and can be re-run standalone with
`bbb score --input results/<file>.csv` (no API calls). It compares the model's
answer against the dataset using normalized copies of the names — the dataset on
disk always keeps the official casing and spelling. Normalization is case- and
hyphen-insensitive and strips surrounding punctuation, but does **not** fold
spelling variants (e.g. "Gray" ≠ "Grey") or strip diacritics, since those are
genuine name differences.

Three layers of metrics are recorded per row:

1. **`exact_match`** — the normalized response equals the CBRO English name.
2. **`acceptable_match`** — the normalized response equals the English name from
   *any* of the three authorities (CBRO, eBird, AviList); `match_source` lists
   which authorities agreed.
3. **Error classification** — for non-matches, `error_type` and
   `taxonomic_distance` (0–4) say *how* wrong the answer is, by looking the
   response up in a taxonomy index built from all three authorities:

   | distance | `error_type`   | meaning                              |
   |---------:|----------------|--------------------------------------|
   | 0        | `correct`      | acceptable match                     |
   | 1        | `intra_genus`  | wrong species, same genus            |
   | 2        | `intra_family` | wrong species, same family           |
   | 3        | `intra_order`  | wrong species, same order            |
   | 4        | `hallucinated` | name not found among known species   |
   | —        | `api_error`    | request failed                       |
   | —        | `truncated`    | generation exhausted its token limit|
   | —        | `empty_response` | completed without answer           |

Rescoring builds its taxonomy index from the complete reference dataset, so a
partial run is classified consistently with a complete run.

## 4. Statistical analysis (`bbb stats`)

```bash
bbb stats \
  --input results/openai--gpt-5.5_no_reasoning.csv \
  --input results/openai--gpt-5.5_reasoning.csv \
  --output results/gpt-5.5_statistics.csv
```

This reports species-level percentile bootstrap 95% confidence intervals and,
with multiple inputs, pairwise two-sided exact McNemar tests. Observations are
paired by `cbro_id`; partial runs use their shared species and report that size.

## 5. Auditing (`bbb audit`)

```bash
bbb audit --input results/<file>.csv --sample 50
```

`bbb audit` draws a reproducible random sample (`--seed`) of wrong answers into
`audit/<input-stem>_audit.csv` with an empty `human_label` column for manual
review. After labelling and adjusting the classifiers, re-run `bbb score` to
re-apply scoring.

## Results

Benchmarks run June 2026 via OpenRouter — zero-shot, `temperature 0`, single run
per species, **1,836 scored species** (those with both an eBird and AviList
match). `no_reasoning` snapshot: 2026-06-24 · `reasoning` snapshot: 2026-06-29
(see the `benchmarks-*` git tags). `accept` = the answer matches the English name
of any of the three authorities (CBRO/eBird/AviList). `qwen3.7-plus` reasoning is
a **partial run (655/1,836 rows)** — its percentages are not directly comparable.

### Accuracy (acceptable match)

| Model | no_reasoning | reasoning |
|-------|-------------:|----------:|
| openai/gpt-5.5               | 33.44% | **73.04%** |
| anthropic/claude-opus-4.8    | 32.19% | 48.64% |
| google/gemini-3.1-flash-lite | 32.41% | 45.04% |
| deepseek/deepseek-v4-pro     | 30.88% | 42.32% |
| anthropic/claude-sonnet-4.6  | 24.56% | 38.29% |
| openai/gpt-5.4-mini          | 18.79% | 29.30% |
| moonshotai/kimi-k2.6         | 18.95% | 26.09% |
| qwen/qwen3.7-plus            | 20.37% | 29.01%* |
| mistralai/mistral-small-2603 | 16.34% | 18.85% |

<sub>* partial run (655 rows)</sub>

### Error types — no_reasoning

| Model | correct | intra_genus | intra_family | intra_order | hallucinated | API error | truncated |
|-------|--------:|------------:|-------------:|------------:|-------------:|----------:|----------:|
| openai/gpt-5.5               | 614 | 143 | 350 | 255 | 474 | 0 | 0 |
| anthropic/claude-opus-4.8    | 591 | 172 | 389 | 231 | 453 | 0 | 0 |
| google/gemini-3.1-flash-lite | 595 | 154 | 401 | 222 | 464 | 0 | 0 |
| deepseek/deepseek-v4-pro     | 567 | 121 | 336 | 252 | 557 | 3 | 0 |
| anthropic/claude-sonnet-4.6  | 451 | 139 | 342 | 234 | 670 | 0 | 0 |
| openai/gpt-5.4-mini          | 345 |  63 | 235 | 248 | 945 | 0 | 0 |
| moonshotai/kimi-k2.6         | 348 | 107 | 271 | 341 | 761 | 0 | 8 |
| qwen/qwen3.7-plus            | 374 |  82 | 221 | 170 | 989 | 0 | 0 |
| mistralai/mistral-small-2603 | 300 |  53 | 297 | 265 | 921 | 0 | 0 |

### Error types — reasoning

| Model | correct | intra_genus | intra_family | intra_order | hallucinated | API error | truncated |
|-------|--------:|------------:|-------------:|------------:|-------------:|----------:|----------:|
| openai/gpt-5.5               | 1341 |  91 | 117 |  71 | 214 | 0 |   2 |
| anthropic/claude-opus-4.8    |  893 | 182 | 316 | 136 | 302 | 0 |   7 |
| google/gemini-3.1-flash-lite |  827 | 182 | 317 | 137 | 373 | 0 |   0 |
| deepseek/deepseek-v4-pro     |  777 | 115 | 289 | 211 | 365 | 7 |  72 |
| anthropic/claude-sonnet-4.6  |  703 | 138 | 338 | 205 | 449 | 0 |   3 |
| openai/gpt-5.4-mini          |  538 | 104 | 200 | 153 | 841 | 0 |   0 |
| moonshotai/kimi-k2.6         |  479 |  69 | 190 | 191 | 315 | 4 | 588 |
| qwen/qwen3.7-plus *(partial)* | 190 |  37 | 101 |  10 | 315 | 2 |   0 |
| mistralai/mistral-small-2603 |  346 |  86 | 269 | 192 | 900 | 0 |  43 |

<sub>`correct` = acceptable match. Counts are per scored species; rows sum to
1,836 (655 for the partial qwen run). Reasoning lifts accuracy for every model,
but some runs frequently exhaust their token limit (Kimi: 588; DeepSeek: 72).</sub>

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check .
```

## Methodology and citation

The frozen v1.0 experimental protocol, statistical procedure, limitations, and
reproducibility notes are documented in [METHODS.md](METHODS.md). Citation
metadata is provided in [CITATION.cff](CITATION.cff).

## License

The code is distributed under the [MIT License](LICENSE). The CBRO checklist,
eBird taxonomy, and AviList checklist retain their own terms; see their
respective sources before redistribution.
