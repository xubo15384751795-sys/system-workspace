# Research Corpus

## 1. Dataset Role

Research corpus materials are narrative, institutional, and literature context.
They are not formal market data by default.

## 2. Source And Access

Materials are archived under `data/raw/research_corpus/` and described by
manifests under `data/manifests/research_corpus/`.

## 3. Frequency Policy

No market-data frequency is assumed. Publication date and access date are
metadata, not a tradable time series.

## 4. Allowed Uses

- macro regime language
- institution context
- methodology reference
- fund behavior sample
- case context
- writing style reference

## 5. Forbidden Uses

- `M/D/K/X` proxy core construction
- `Sigma_t` construction
- formal market-data evidence
- benchmark panel construction

## 6. Manifest Requirements

- provider
- title
- publication date when available
- URL
- local path
- file hash
- document type
- topics
- asset class
- strategy family
- usage tags
- `allowed_for_proxy_core=false` by default

## 7. Related Code

- `src/research_corpus/`
- `docs/contracts/research_corpus_contract.md`
- `docs/schemas/research_corpus_manifest.schema.json`

## 8. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
