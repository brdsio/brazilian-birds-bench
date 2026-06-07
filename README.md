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

## Pipeline

The CLI is exposed as `bbb`.

### 1. Parse the CBRO checklist

```bash
# download the spreadsheet from Zenodo and parse it
bbb parse --download

# or parse a local copy
bbb parse --input data_raw/cbro_2021.xlsx
```

Produces `brazilian_birds_bench/data/cbro_species.csv`: one row per species,
with scientific name, taxonomy (order / family / genus), Portuguese and English
names, and the CBRO status field decomposed into structured columns
(`occurrence`, `endemic_brazil`, `extinct`, `introduced`, `status_uncertain`,
`origin_directions`).

### 2. Enrich with eBird English names

Get an eBird API token at https://ebird.org/api/keygen, then copy the example
env file and fill it in:

```bash
cp .env.example .env
# edit .env and set EBIRD_API_TOKEN=your_token_here
```

The token is loaded automatically from `.env` (no manual `export` needed):

```bash
bbb enrich
```

You can still override it ad hoc with `bbb enrich --token your_token_here`.

Downloads the full eBird taxonomy in a single request and merges by scientific
name, adding `english_name_ebird`, `ebird_species_code`, `ebird_matched`, and
`name_disputed` (true when eBird and CBRO disagree on the English name).

### 3. Enrich with AviList English names (third authority)

Download the AviList Short spreadsheet automatically and enrich in one step:

```bash
# fetch the Short spreadsheet to data_raw/avilist_v2025_short.xlsx, then enrich
bbb enrich-avilist --download

# or point at a copy you already have (e.g. the Extended version)
bbb enrich-avilist --avilist-file data_raw/avilist_v2025_short.xlsx
```

`--download` pulls the v2025 (11-Jun) Short spreadsheet directly from
[avilist.org](https://www.avilist.org/checklist/v2025/). Once the file is
present the command runs fully offline. Merges by scientific name and adds
`english_name_avilist`,
`avilist_matched`, and `name_disputed_avilist`. You can chain it on top of the
eBird output (`--input ...cbro_species_ebird.csv`) to triangulate all three
authorities in a single file.

## Development

```bash
uv pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT for the code. The CBRO checklist and eBird taxonomy retain their own terms;
see their respective sources before redistribution.
