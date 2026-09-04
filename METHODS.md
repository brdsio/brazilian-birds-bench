# Benchmark protocol

This document describes the Brazilian Birds Bench v1.1 release. It retains the
frozen v1.0 experimental protocol and adds two reasoning-model result sets.
It should be read with the versioned configuration, dataset, result CSVs, and
statistical reports distributed in this repository.

## Research question

The benchmark measures whether a language model can map a Brazilian Portuguese
bird common name to an accepted English common name without examples,
retrieval, tools, or conversational context. It is a narrow probe of knowledge
available to the model in a zero-shot, single-turn setting; it is not a general
ornithology or translation benchmark.

## Reference dataset

The source population is the 1,971 species in the 2021 checklist of the
Comitê Brasileiro de Registros Ornitológicos (CBRO). Records are enriched by
scientific name with English names and taxonomy from eBird/Clements and AviList
v2025. Exact binomial matching is attempted first, followed by a conservative
epithet-and-family match for genus changes. Match methods and disagreements are
retained as columns.

The evaluated population contains the 1,836 records matched to both eBird and
AviList. This eligibility rule was fixed before the reported model runs. The
versioned `src/data/benchmark_dataset.csv` is the evaluation reference; future
taxonomy updates constitute a new benchmark version rather than an in-place
change to v1.0.

## Prompt and generation

Each eligible Portuguese name is sent in an independent request. The system
message is:

> You are an ornithology expert. When given a Brazilian Portuguese bird common
> name, respond with only its English common name. Do not include any
> explanation, punctuation, or additional text.

The user message contains only the Portuguese common name. The benchmark is
zero-shot and uses no retrieval or tools. Reported runs used temperature 0 and
one request per species. Temperature 0 does not guarantee deterministic hosted
inference, and the absence of repeated runs is a limitation of v1.0.

Models were called through OpenRouter's OpenAI-compatible Chat Completions API.
The model ID, requested reasoning configuration, latency, token usage, finish
reason, and raw response are stored per row. Historical runs predate the v1.0
manifest support and do not contain a provider identity or independently
verified effective reasoning configuration. New runs fail rather than silently
changing a rejected reasoning protocol and write a manifest containing hashes,
runtime versions, routing policy, and generation settings.

## Reasoning conditions

`no_reasoning` requested `reasoning.effort: none`. `reasoning` used the
model-specific configuration in `benchmark_config.json`. These settings are
not necessarily computationally equivalent across model families: some use an
effort label and others a fixed reasoning-token budget. Comparisons between
conditions therefore describe the configured products, not a controlled equal
compute intervention.

The original no-reasoning runs were captured on 2026-06-24 and the original
reasoning runs on 2026-06-29. The Fable 5.1 and GPT-5.6 reasoning runs added in
v1.1 were captured on 2026-09-02. The Qwen reasoning run was deliberately
stopped after 655 of 1,836
species because of excessive latency and poor interim performance; it is
reported as partial and is not directly comparable to complete-run percentages.

## Scoring

Normalization is applied symmetrically to responses and references. It uses
Unicode case folding, treats hyphens and slashes as spaces, removes remaining
punctuation, and collapses whitespace. It does not merge lexical variants such
as *gray* and *grey* or remove diacritics.

The reported outcomes are:

- `exact_match`: response equals the normalized CBRO English name;
- `acceptable_match`: response equals the normalized English name supplied by
  CBRO, eBird, or AviList;
- `match_source`: authorities supporting an acceptable answer;
- taxonomic error distance: same genus, family, order, or name absent from the
  benchmark taxonomy index;
- `generation_status`: complete, API error, truncated, or empty response.

The primary accuracy shown in the README is `acceptable_match`. API failures,
truncations, and empty responses remain in the denominator. Scoring partial
runs uses the same complete 1,836-species taxonomy index as full runs.

## Statistical analysis

Uncertainty is estimated by a percentile bootstrap over species with 10,000
resamples and seed 42. Reports contain the point estimate and 95% interval.
Pairwise comparisons use a two-sided exact McNemar test, paired by `cbro_id`.
Comparisons involving a partial run use only shared species and report the
paired sample size. The reports contain unadjusted pairwise p-values; readers
performing families of comparisons should apply an appropriate multiplicity
correction.

## Reproducibility and audit trail

Raw model responses are retained in `results/`. The tags
`benchmarks-no_reasoning-2026-06-24` and
`benchmarks-reasoning-2026-06-29` preserve the original result snapshots. Tag
`v1.0` identifies the publication-ready protocol, corrected derived
classifications, and original statistical reports. Tag `v1.1` adds the Fable
5.1 and GPT-5.6 reasoning results without changing the reference dataset or
scoring protocol. Dataset, prompt, and configuration hashes are recorded
automatically for new runs.

## Limitations

- Public bird checklists may have appeared in model training data, so the task
  measures recall or learned mapping rather than discovery.
- A single generation per species does not measure inference variance.
- Model aliases, providers, and hosted implementations may change over time.
- Reasoning configurations differ across vendors and are not equal-compute.
- Exact-string evaluation may reject legitimate variants absent from all three
  reference authorities.
- Taxonomic distance is limited to the benchmark's name index and hierarchy.
- The CBRO 2021 and AviList 2025 snapshots will become outdated; v1.0 keeps
  them fixed to preserve comparability.

## Data and software licensing

The benchmark software is released under the MIT License. Source checklists
and derived taxonomic data retain the terms of CBRO, eBird/Clements, and
AviList. Users redistributing or adapting the dataset are responsible for
complying with those source terms.
