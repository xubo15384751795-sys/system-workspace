# Harvester Design Decisions

This file is append-only. Every architectural decision that shapes the
Harvester repository or its protocol surface is recorded here at the moment
it is made, with the alternatives considered and the rationale that was
load-bearing at the time. Future readers should be able to reconstruct
*why* without having to re-derive it from code.

Format: each decision is `DD-NNN: short title` plus four fixed sections.
Numbers are never reused. Superseded decisions stay in place; a later DD
links back and explains the change.

---

## DD-001: Repository naming uses three layers

- **Decision:** Three distinct names are used for this project, each at
  its own layer:
    - Filesystem directory name: `Structural Risk Harvester/` (with
      spaces and capitalization, sibling of `Structural Deformation
      Research System/` under `/Users/a1/System/`).
    - Python import package: `harvester` (lowercase, no spaces, no
      hyphens). Code reads `import harvester`, `from harvester.core
      import manifest`.
    - PyPI distribution name in `pyproject.toml`: `structural-risk-
      harvester` (hyphenated, PEP 503-normalized).
    - Documentation short-name: `Harvester` (capitalized, used as the
      proper noun for the system).
- **Date:** 2026-04-26
- **Rationale:** The filesystem name was inherited from the existing
  empty skeleton and is the user-facing label they recognize. The
  Python package cannot share that name because import paths cannot
  contain spaces. The PyPI name follows the same family style as the
  sibling project (`structural-deformation-research-system`) so that
  if both are ever published or vendored together, their distribution
  names sort and read consistently. The doc short-name keeps prose
  readable.
- **Alternatives considered:**
    - Rename the directory to `Harvester/` to match the doc
      short-name. Rejected: would diverge from the sibling
      `Structural Deformation Research System/` and break the user's
      mental model of `/Users/a1/System/` as a workspace of
      long-named, sibling research systems.
    - Use `structural_risk_harvester` (underscores) as the import
      package. Rejected: longer, redundant with the PyPI name, and
      Harvester is the user-facing identity inside this repo — there
      is no risk of collision with another `harvester` package
      because this codebase is not on PyPI.

---

## DD-002: Empty placeholder directories deleted; src-layout adopted

- **Decision:** The four pre-existing empty directories
  (`harvester/`, `configs/`, `docs/`, `tests/`) under `Structural
  Risk Harvester/` were deleted. The Python package was then
  recreated under `src/harvester/` (true src-layout). `tests/` and
  `docs/` were recreated with real content rather than left as
  placeholders.
- **Date:** 2026-04-26
- **Rationale:** The original `harvester/` was a flat package at the
  repo root, which makes editable installs subtly wrong (the repo
  root ends up on `sys.path` and every top-level file becomes
  importable). Src-layout forces installs to go through
  `pyproject.toml` and removes the chance of accidentally importing
  uncommitted scratch files at the repo root. Since `harvester/` had
  to move anyway, the other three empty placeholders were swept up
  in the same operation rather than left as semantically-empty
  directories alongside real ones.
- **Alternatives considered:**
    - Keep `harvester/` at the repo root (flat layout). Rejected per
      above: weaker isolation, encourages root-dir scratch imports.
    - Keep the empty `configs/`, `docs/`, `tests/` until they were
      naturally needed. Rejected: mixing empty and populated
      directories at the same level is a readability cost for no
      benefit.

---

## DD-003: `data/` symlink defines the protocol-governed surface; provider-internal dirs are out of scope

- **Decision:** All bulk data lives under the `data/` symlink, which
  points to `/Users/a1/System/Data/harvester/` (a non-versioned data
  volume, not part of any git repository). Within that volume, the
  directories are split into two classes:
    - **Protocol-governed (in scope):** `data/exports/`,
      `data/manifests/`, `data/provenance/`, `data/quality_reports/`.
      These are the surface that consumers — currently Deformation
      via `src/data_access/harvester_adapter.py` — are allowed and
      expected to read.
    - **Provider-internal (out of scope):** `data/raw/`,
      `data/processed/`, `data/corpus/`. These are working
      directories owned by individual provider implementations
      (raw scrapes, intermediate ETL output, institutional text
      caches). Their contents do not appear in any `catalog.json`
      and consumers MUST NOT read from them. A provider that needs
      to expose any of this content to consumers must promote it
      into a manifested dataset under `data/exports/`.
- **Date:** 2026-04-26
- **Rationale:** Code and data must be separated for the same reasons
  Deformation already uses a `data/` symlink: bulk artifacts cannot
  go into git, and a symlink is the cleanest physical implementation
  of that separation. The in-scope vs. out-of-scope distinction
  exists to prevent the protocol from being silently bypassed: if
  consumers can read `data/raw/` directly, the manifest+sha256
  contract is decorative. Naming the boundary explicitly here, and
  echoing it in `contracts/access_protocol.md`, makes future
  protocol violations visible during review rather than discovered
  in production.
- **Alternatives considered:**
    - Put `exports/`, `manifests/`, `provenance/`,
      `quality_reports/` directly in the repo root and ignore the
      `data/` symlink. Rejected: forces git to track or ignore-
      large-files-by-pattern, breaks symmetry with Deformation,
      and creates two competing locations for "where does the data
      live."
    - Move the provider-internal dirs (`raw/`, `processed/`,
      `corpus/`) somewhere outside `data/`. Rejected: providers
      legitimately need a working area on the same volume as their
      output (atomic renames, shared filesystem semantics). The
      protocol document is the right place to draw the line, not
      the directory tree.

---

## DD-004: `harvester_adapter` consumes paths from config; no fallback

- **Decision:** In Phase 4, `Structural Deformation Research
  System/src/data_access/harvester_adapter.py` will be rewritten so
  that `harvester_root` is read exclusively from
  `Deformation/config.yaml`'s `harvester.root` field. The current
  `_default_export_root()` fallback will be deleted. Missing config,
  missing path, or unreadable catalog will raise immediately at
  startup with an error message that names the expected config
  field, the value that was actually read, and the suggested fix.
  Relative paths in the config are resolved against the Deformation
  repository root (located via a marker file or `pyproject.toml`),
  not against the process CWD.
- **Date:** 2026-04-26
- **Rationale:** The existing fallback computed
  `parents[2].parent / "structural-risk-harvester" / ...`, which
  resolved to a path that has never existed (lowercase, hyphenated,
  while the real directory is `Structural Risk Harvester` with
  spaces). The adapter has therefore been silently
  misconfigured-by-default since it was written, and any caller who
  forgot to pass `export_root` would get a `HarvesterBundleMissingError`
  pointing at a phantom path. Removing the fallback turns this
  class of bug into a startup-time crash with an actionable message,
  which is strictly better than a fallback that points nowhere.
- **Alternatives considered:**
    - Fix the fallback to point at the real directory. Rejected:
      preserves the silent-failure surface; the next time the
      directory layout changes, the same bug recurs.
    - Resolve relative paths against process CWD. Rejected: brittle
      under different invocation contexts (notebooks, tests,
      scripts run from subdirs).

---

## DD-005: Harvester adopts true src-layout; intentional divergence from Deformation

- **Decision:** Harvester's `pyproject.toml` uses
  `[tool.setuptools.packages.find] where = ["src"]`, which exposes
  packages under `src/` as top-level imports — i.e. `import
  harvester` works, `import src.harvester` does not. Deformation's
  `pyproject.toml`, by contrast, uses `include = ["src*"]`, which
  treats `src` itself as a top-level namespace and forces the
  `src.` prefix on all imports. The two layouts are intentionally
  different at this stage; Harvester does not adopt Deformation's
  pattern.
- **Date:** 2026-04-26
- **Rationale:** Harvester is a greenfield repository with no
  legacy callers, so it gets to use the convention modern Python
  packaging actually recommends (PEP 517/518 src-layout, packages
  importable by their real name). Making consumers write `import
  harvester` is also the boundary statement we want with
  Deformation: Harvester is *a peer system*, not a subdirectory of
  one. Forcing a `src.` prefix in imports would suggest otherwise.
  Migrating Deformation to the same layout is a separate, larger
  task because Deformation has hundreds of `from src.X import ...`
  call sites; doing it here would be out of scope and risky.
- **Alternatives considered:**
    - Mirror Deformation's `include = ["src*"]` for symmetry.
      Rejected: would force `import src.harvester` everywhere,
      contradicting DD-001's import-name decision and creating a
      package whose import path doesn't match its identity.
    - Use a flat layout (no `src/` directory). Rejected per
      DD-002.
- **Future work:** When Deformation's layout is eventually
  modernized, both repos should use `where = ["src"]`; cite this DD
  in that future migration.

---

## DD-006: Phase 2 contracts frozen at schema family version 1.0

- **Decision:** The four contract files (`access_protocol.md`,
  `catalog.schema.json`, `dataset_manifest.schema.json`,
  `provenance.schema.json`) are frozen as of 2026-04-26 at schema
  family version 1.0. Any change to field names, regex patterns,
  enum values, `required` lists, `additionalProperties` settings,
  or the boundary statements in the protocol document requires a
  schema version bump (MINOR for backwards-compatible additions,
  MAJOR for breaking changes) per `access_protocol.md` §7. The
  files were authored externally (in conversation with the user)
  and adopted verbatim — no editorial changes were made by the
  implementer in this phase.
- **Date:** 2026-04-26
- **Rationale:** Phase 3 implementation will encode these schemas
  as the source of truth. Freezing them before any code is written
  prevents the contracts from drifting under implementation
  pressure (e.g., "this field is awkward to populate, let's drop
  it"). Adopting the spec verbatim, rather than paraphrasing,
  preserves the exact wording the user reviewed and approved —
  paraphrase-induced drift is a real source of contract bugs in
  multi-author systems.
- **Alternatives considered:**
    - Allow Phase 3 to revise contracts as implementation reveals
      issues. Rejected: removes the value of Phase 2 as a review
      gate; turns "frozen" into "tentative."
    - Defer freezing until at least one provider is implemented
      and exercises the schemas. Rejected: would couple the
      protocol's stability to the timing of provider work, and
      the user explicitly required a freeze + review gate before
      Phase 3.
- **Validation performed:**
    - All three JSON schemas pass meta-validation against the
      Draft 2020-12 meta-schema.
    - `release_id`, `dataset_id`, `schema_version`, `sha256`, and
      `git_commit` regex patterns are byte-identical wherever
      they appear across the three schemas.
    - Path patterns for `manifest_path`, `data_path`,
      `provenance_path`, and `quality_report_path` agree between
      `catalog.schema.json` and `dataset_manifest.schema.json`.
- **Reference:** Spec authored in conversation; see commit
  message for Phase 2 commit.

---

## DD-007: §12 boundary clarifications appended to access_protocol

- **Decision:** Section §12 ("Notes on 1.0 boundaries") was appended
  to `contracts/access_protocol.md` to make four boundary
  interpretations explicit before Phase 3 implementation begins:
    - **§12.1 Vintage granularity** — `vintage_date` in 1.0 is
      dataset-level only. Row-level vintage is deferred to schema
      family 1.1 and will not be added as an optional field within
      1.0 (which would silently bifurcate the protocol surface).
      Revising series (NFCI, OFR FSI, FRED) must be republished as
      new releases.
    - **§12.2 Cross-system derivation identity** — when a derived
      dataset is produced by a system outside Harvester (e.g.,
      Deformation depositing a proxy back into Harvester), the
      external system's commit and config MUST be recorded inside
      `provenance.transformations[].code_reference` and `params`.
      Schema 1.0 deliberately does not introduce a dedicated
      `external_system` field; the responsibility lives in provider
      discipline.
    - **§12.3 transformations semantics** — the `transformations`
      array is an append-only audit log including `failed` and
      `skipped` outcomes. `checksums.final_sha256` is the sole
      authoritative source of the final hash; deriving the final
      hash from `transformations[-1].output_sha256` is a protocol
      violation.
    - **§12.4 Empty-dataset releases** — permitted by the schema
      (`datasets.minItems: 0`), but `notes` MUST be non-empty when
      `datasets` is empty. Enforcement is delegated to a future
      audit rule in `scripts/audit_research_os.py` (Phase 5);
      until then providers self-enforce.
- **Date:** 2026-04-26
- **Rationale:** §12 was authored to close ambiguities surfaced
  during Phase 2 review. Without it, Phase 3 implementation
  (especially `exporter.py` and any consumer-side derivation logic)
  would re-derive these boundary calls inconsistently. Writing them
  down inside the protocol document, not as separate notes,
  guarantees they are read by anyone who reads the protocol.
- **No schema files were modified. No version bump.** Schema
  family remains 1.0. The three `.schema.json` files are unchanged
  byte-for-byte from the Phase 2 freeze (commit 7a2d590).
- **Forward link:** §12.4 implies a future Phase 5 audit rule
  ("AR-XX: empty-datasets release MUST have non-empty notes"). The
  rule is not yet implemented; this DD is the placeholder reminder.
- **Reference:** Continuation of the Phase 2 conversation.

---

## DD-008: Artifact store mode, not service mode

- **Decision:** Harvester publishes immutable filesystem artifacts rather than
  running as a long-lived service.
- **Date:** 2026-04-26
- **Rationale:** The immediate consumer is a research system that needs
  reproducibility, auditability, and point-in-time replay more than low-latency
  online serving. Artifact bundles can be pinned by `release_id`, copied,
  checksummed, archived, and inspected with ordinary tools. A service would add
  lifecycle, network, auth, caching, deployment, and availability concerns
  before there is a need for them.
- **Alternatives considered:**
    - Expose a local HTTP API. Rejected: introduces mutable runtime behavior
      and operational state that weakens paper-grade reproducibility.
    - Import Harvester directly from Deformation. Rejected: makes Harvester a
      library dependency instead of a peer system and bypasses the frozen file
      protocol.

---

## DD-009: Releases are immutable and versioned

- **Decision:** A finalized release directory `YYYY-MM-DD-rN/` is immutable.
  Corrections use a new release, usually `rN+1` on the same date. `latest` is a
  convenience symlink to the newest finalized release, not a reproducibility
  identifier.
- **Date:** 2026-04-26
- **Rationale:** Research conclusions must be tied to the exact bytes loaded at
  the time of analysis. Mutating an old export would make historical notebooks,
  reports, and paper drafts ambiguous. Versioned immutable releases keep bad or
  superseded artifacts auditable without letting them silently change.
- **Alternatives considered:**
    - Rewrite `latest` in place and discard older bundles. Rejected: convenient
      for exploration, unsafe for reproducibility.
    - Keep one release per calendar day only. Rejected: same-day corrections are
      normal; `r1`, `r2`, ... represent that reality without inventing fake
      dates.

---

## DD-010: Manifest time semantics separate `as_of_date` and `vintage_date`

- **Decision:** Every dataset manifest carries both `as_of_date` and
  `vintage_date`.
- **Date:** 2026-04-26
- **Rationale:** Financial and institutional datasets often describe one date
  while becoming available on another. A point-in-time consumer needs both
  dates to avoid lookahead bias. `as_of_date` answers "what world state does
  this describe"; `vintage_date` answers "when could the consumer have known
  it."
- **Alternatives considered:**
    - Use one date field. Rejected: conflates observation time and publication
      time.
    - Make vintage optional. Rejected: optional vintage would make no-lookahead
      enforcement depend on dataset-specific convention.

---

## DD-011: Harvester never imports Deformation

- **Decision:** No code in Harvester imports Deformation, ever.
- **Date:** 2026-04-26
- **Rationale:** Harvester is the producer of data artifacts; Deformation is one
  consumer. If Harvester imports Deformation, provider code can start depending
  on interpretive models, configs, or runtime state, and the data layer becomes
  theory-aware. That would violate the central rule: Harvester does not
  interpret or theorize.
- **Alternatives considered:**
    - Share utility modules by import. Rejected: shared code should be extracted
      deliberately or represented in artifacts, not imported across the peer
      boundary.
    - Let Harvester call Deformation to produce derived datasets. Rejected:
      derived datasets may record Deformation commits/config in provenance, but
      Harvester still publishes the resulting bytes through the same manifest
      protocol.
