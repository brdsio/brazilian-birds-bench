# brazilian-birds-bench

A benchmark of large language model knowledge on Brazilian bird names.

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

## Usage

The CLI is exposed as a single command, `bbb`, that builds the whole dataset in
one shot.

### 1. Configure the eBird token

Get an eBird API token at https://ebird.org/api/keygen, then copy the example
env file and fill it in:

```bash
cp .env.example .env
# edit .env and set EBIRD_API_TOKEN=your_token_here
```

The token is loaded automatically from `.env` (no manual `export` needed). You
can also pass it ad hoc with `bbb --token your_token_here`.

### 2. Build the dataset

```bash
bbb
```

`bbb` runs every stage end-to-end and writes a single
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

Useful options (`bbb --help` for the full list):

```bash
bbb --output data/birds.csv      # change the output path
bbb --no-download                # require local source files, never fetch
bbb --cbro-file path/to.xlsx     # use a specific CBRO / AviList copy
bbb --locale pt                  # eBird common-name locale (default: en)
```

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT for the code. The CBRO checklist and eBird taxonomy retain their own terms;
see their respective sources before redistribution.
