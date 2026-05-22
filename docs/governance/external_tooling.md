# External Tooling for Test/Audit Acceleration

## 1. pytest with markers

We use pytest markers to partition the test suite into targeted groups.
This avoids running the full 700+ test suite during every promotion check.

### Marker reference

| Marker | What it guards | Approx. count |
|---|---|---|
| `critical_gate` | Routing gate, config audit, force promotion trace | ~11 |
| `semantic` | Concept registry, proxy semantics, NOT_IMPLEMENTED | ~12 |
| `data_boundary` | Boundary, freshness, provenance, Harvester adapter | ~15 |
| `benchmark` | Qlib placeholder, comparison validity | ~6 |
| `report` | Report verdict gate, export validation | ~5 |
| `governance_loop` | Ledger, escalation, incident lifecycle | ~6 |
| `slow` | Long-running tests (>10s) | ~0 (add as needed) |

### Quick commands

```bash
# Fastest — critical gates only (~10s)
pytest -n auto -m critical_gate -v

# Pre-promotion — gates + semantics + boundaries (~60s)
pytest -n auto -m "critical_gate or semantic or data_boundary or report" -v

# Full preflight (including SDRS framework tests)
cd structural_deformation_research_system
pytest -n auto -m "semantic or data_boundary or benchmark" -q

# From project root with Justfile
just smoke       # critical_gate + semantic
just promotion   # full preflight including semgrep
just nightly     # everything
```

## 2. pytest-xdist

Installed via `pip install pytest-xdist`. Use `-n auto` to parallelise
by CPU core count. On an 8-core machine this cuts ~120s suite → ~30s.

## 3. semgrep

Installed via `pip install semgrep`. We ship five custom rules:

| Rule file | What it catches |
|---|---|
| `semgrep_rules/http-acquisition.yaml` | Direct HTTP fetch in Deformation core (DATA_BOUNDARY.md) |
| `semgrep_rules/silent-except-pass.yaml` | `except Exception: pass` in promote_snapshot/gate code |
| `semgrep_rules/legacy-backend.yaml` | Hardcoded `"legacy"` default where `"harvester"` is required |
| `semgrep_rules/force-accountability.yaml` | `--force` without `--authorized-by` / `--reason` |
| `semgrep_rules/missing-report-verdict.yaml` | Report generated without `validate_report_verdict()` |

Usage:

```bash
semgrep --config=semgrep_rules/ --error
```

The `just promotion` target runs semgrep after tests.

## 4. Recommended CI flow

```
just smoke          # 30s  — fast feedback
just promotion      # 90s  — pre-promotion gate
just nightly        # 300s — full regression (scheduled or on merge)
```

## 5. Build system recommendation: skip Pants/Bazel for now

**Recommendation:** Do NOT adopt Pants, Nx, or Bazel at this stage.

| Tool | Cost to adopt | Benefit for this project |
|------|---------------|--------------------------|
| **pytest + xdist** | Zero (already using pytest) | Cuts test time 4× on 8-core machine |
| **semgrep** | `pip install` | Catches 5 governance anti-patterns |
| **just** | `brew install` | Names the 6 common test targets |
| **Pants** | 2-3 days to migrate BUILD files | Remote caching helps only if CI is the bottleneck |
| **Bazel** | 1-2 weeks + `BUILD` per directory | Overkill: no C++/Java/Rust, no monorepo, no container builds |
| **Nx** | 1 day to wire task graph | Adds graph abstraction without meaningful computation |
| **nox** | `pip install` | Reasonable alternative to Justfile, but less ergonomic |

**Why not Pants:**

- This project has no heterogeneous-language builds (pure Python).
- There is no monorepo spanning multiple build systems.
- Test isolation is already handled by pytest-xdist.
- Dependency caching is not a bottleneck: pip install is <10s.
- Pants requires `BUILD` files per directory and a non-trivial `pants.toml`.
- The project's test suite is 700 tests, not 70,000 — well within pytest's sweet spot.

**When to revisit:**

- If CI test time exceeds 10 minutes after xdist is in use.
- If you add C++/Rust extensions or a second language.
- If the test suite grows beyond 5,000 tests and remote caching becomes valuable.

### What to do instead

1. `pip install pytest-xdist semgrep`
2. `brew install just`
3. Run `just promotion` before every promotion
4. Add `just nightly` to a weekly CI schedule
5. Revisit this decision when CI test time exceeds 10 minutes

## 6. External Tool Integration — Routing Decisions

The following routing decisions govern the integration of three external tools
(OpenBB, GluonTS, Qlib) into the system. Each decision is a YAML artifact in
`Output/system_learning/routing_decisions/`.

| Decision ID | Tool | Scope | Key constraint |
|---|---|---|---|
| `2026-05-17-catalog-protocol-unification` | None (protocol) | DataHubLite + freshness dataset-mode | Consumer-side protocol fix, no producer changes |
| `2026-05-17-openbb-acquisition-consolidation` | OpenBB | Harvester provider consolidation | OpenBB only in Harvester; boundary test enforced |
| `2026-05-17-qlib-executor-promotion` | Qlib | Real Qlib binary dump + anti-gaming | Qlib stays file-isolated sandbox; anti-gaming guards placeholder metrics |
| `2026-05-17-gluonts-probabilistic-forecasting` | GluonTS | Probabilistic regime + anomaly | Add-alongside, not replace; regime path uses runnable SeasonalNaive baseline |

All decisions pass through: routing_gate → decision_trace → semantic_registry → module_authority.
