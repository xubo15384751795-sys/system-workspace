# Legacy Data Audit Template

Use this file to inventory the existing in-project data layer before any
migration. Do not delete or move files during this audit.

## Scope

- Audit date:
- Auditor:
- Data root:
- Project commit/branch:
- Frozen legacy status: yes/no

## Inventory Table

| ID | Path | File type | Owner module/script | Source clarity | Series/entities | Usage | Dependencies | Frequency | Missing policy | Look-ahead risk | Current tag | Migration target | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L001 | `data/...` | parquet/csv/json/duckdb/pdf | `src/...` | clear/partial/unknown | series list | proxy/benchmark/corpus/cache/output | scripts/tests/modules | daily/weekly/monthly/unknown | explicit/implicit/unknown | low/medium/high/unknown | proxy/benchmark/corpus/legacy | harvester export / keep frozen / retire |  |

## Connector Inventory

| Connector/script | Path | Provider | Output paths | Source clarity | Frequency policy | Missing policy | Look-ahead risk | Still used by | Migration target |
|---|---|---|---|---|---|---|---|---|---|
| DataHubBridge | `src/data/gateway/bridge.py` | mixed | current data root | partial | config dependent | fallback/mock | medium until audited | pipeline/tests | adapter consumer |

## Series Inventory

| Series ID | Provider | Role tag | Proxy/benchmark/corpus | Frequency | Source URL/API | Transformations | Missing policy | Look-ahead notes | Migration target |
|---|---|---|---|---|---|---|---|---|---|
| `FRED:VIXCLS` | FRED | benchmark/control | benchmark | daily |  |  |  | release timing required | harvester benchmark panel |

## Usage And Dependency Notes

- Which tests depend on this data?
- Which scripts write or mutate this data?
- Which modules read it directly?
- Which outputs are paper-facing?

## Migration Decision

| Data asset | Decision | Target | Required checks before migration |
|---|---|---|---|
|  | keep frozen / export via harvester / retire |  | manifest, source registry, no-lookahead, tag validation |

## Open Risks

- Source clarity gaps:
- Frequency/release-lag gaps:
- Missingness gaps:
- Look-ahead risks:
- Benchmark/proxy contamination risks:
- Corpus/formal-data contamination risks:
