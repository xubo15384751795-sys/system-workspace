"""Minimal pipeline DAG for failure propagation.

Phase A scope: compute the upstream set of a step from the registry's declared
``contracts.inputs`` / ``contracts.outputs`` edges, so the daily-run executor
can block a step when any required upstream failed.

This is deliberately *not* a full DAG compiler (that is Phase B). It exposes
exactly what failure propagation needs:

- ``upstream_of(step_id)`` -> list of producer step ids whose declared outputs
  overlap this step's declared inputs (path-prefix match, since a producer may
  declare an output *directory* while a consumer declares a file inside it).
- ``failure_behavior_of(step_id)`` -> the declared failure_behavior string,
  used to decide whether an upstream failure should propagate *through* a step
  (block_*) or be tolerated (continue_with_warning).

Edges are derived from ``governance/daily_pipeline_registry.yaml``. The
registry already declares the authoritative chain::

    structural_replay -> bridge -> judgment_layer -> trade_decision -> paper_portfolio

plus ``structural_replay -> paper_portfolio`` (via all_signals.parquet).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from scripts._pipeline_runner import load_registry


def _contract_paths(step: dict[str, Any], key: str) -> list[str]:
    """Return the list of input/output paths declared in contracts, or []."""
    contracts = step.get("contracts", {}) or {}
    paths = contracts.get(key) or []
    if isinstance(paths, str):
        return [paths]
    return [str(p) for p in paths]


def failure_behavior_of(step_id: str) -> str:
    """Declared failure_behavior for a step (top-level, else authority block).

    Returns "" if unset (the registry default is continue_with_warning, but we
    return empty so callers can distinguish "declared" from "default").
    """
    step = load_registry().get("steps", {}).get(step_id, {})
    fb = step.get("failure_behavior")
    if not fb:
        fb = (step.get("authority") or {}).get("failure_behavior")
    return fb or ""


def _propagates_failure(step_id: str) -> bool:
    """Does this step's failure_behavior propagate failure to descendants?

    A step declares propagation when its failure_behavior is a blocking
    variant. ``continue_with_warning`` (and unset) are leaf-only: their failure
    must NOT block descendants, per the registry's own semantics.
    """
    fb = failure_behavior_of(step_id)
    return fb in {
        "block_current_readout",
        "block_core_judgment",
        "block_promotion",
        "hold_flat",
        "decision_adjacent_block",
    }


@lru_cache(maxsize=1)
def _edges() -> dict[str, list[str]]:
    """Map consumer step_id -> list of producer step_ids.

    A producer P is an upstream of consumer C if some output path of P is a
    prefix of (or equal to) some input path of C. Directory outputs (trailing
    ``/``) match files inside them.

    In-place mutators (a step whose declared input path equals one of its
    declared output paths, e.g. ``refresh_cross_asset_panel`` refreshing
    ``Data/panels/cross_asset_daily_panel.parquet`` in place) are NOT treated
    as producers for other consumers of that path - the path is an external
    input, not produced by the mutator.
    """
    steps = load_registry().get("steps", {})
    # producer step_id -> normalized output paths (no trailing slash), EXCLUDING
    # paths the step also declares as inputs (in-place refresh).
    producer_outputs: list[tuple[str, list[str]]] = []
    for sid, s in steps.items():
        outs = [p.rstrip("/") for p in _contract_paths(s, "outputs") if p]
        ins = {p.rstrip("/") for p in _contract_paths(s, "inputs") if p}
        # Exclude in-place-mutated paths: a step that reads and rewrites the
        # same file is not the authoritative producer for other consumers.
        outs = [o for o in outs if o not in ins]
        if outs:
            producer_outputs.append((sid, outs))

    edges: dict[str, list[str]] = {}
    for cid, c in steps.items():
        ins = [p.rstrip("/") for p in _contract_paths(c, "inputs") if p]
        if not ins:
            continue
        producers: list[str] = []
        for pid, outs in producer_outputs:
            if pid == cid:
                continue
            if any(_path_overlaps(out, ins) for out in outs):
                producers.append(pid)
        if producers:
            edges[cid] = producers
    return edges


def _path_overlaps(producer_out: str, consumer_ins: list[str]) -> bool:
    """True if producer_out is equal to or a prefix of any consumer input."""
    for cin in consumer_ins:
        if cin == producer_out or cin.startswith(producer_out + "/"):
            return True
    return False


def upstream_of(step_id: str) -> list[str]:
    """Producer step ids whose declared outputs feed this step's inputs."""
    return list(_edges().get(step_id, []))


def failed_upstream_of(step_id: str, results: list[dict[str, Any]]) -> list[str]:
    """Upstream steps that have already failed (non-success status).

    ``results`` is the executor's accumulator of step result dicts (each with
    ``step`` and ``status``). A producer counts as failed only if it actually
    propagated (its own failure_behavior is a blocking variant) - a
    ``continue_with_warning`` leaf that failed does NOT block descendants.
    """
    status_by_step = {r.get("step"): r.get("status") for r in results}
    failed: list[str] = []
    for up in upstream_of(step_id):
        st = status_by_step.get(up)
        if st is not None and st != "success" and _propagates_failure(up):
            failed.append(up)
    return failed


# ── Phase B: full DAG compiler + failure_behavior interpreter ────────────


# Steps whose outputs land in the decision-adjacent trees: a failure that
# reaches these must propagate. Used by the "decision-adjacent
# continue_with_warning" structural check.
_DECISION_ADJACENT_TREES = (
    "Output/current/",
    "Output/judgment/",
    "Output/trade_decision/",
    "Output/position/",
    "Output/strategy_lab/shadow",
)

# failure_behavior values that block (or degrade) descendants when the step
# itself fails. ``continue_with_warning`` and ``research_only`` do NOT.
BLOCKING_BEHAVIORS = frozenset({
    "block_current_readout",
    "block_core_judgment",
    "block_promotion",
    "hold_flat",
    "decision_adjacent_block",
})
NON_BLOCKING_BEHAVIORS = frozenset({
    "continue_with_warning",
    "research_only",
    "lower_claim_ceiling",
    "",
})


def _is_external_input(path: str, external_inputs: list[str]) -> bool:
    """True if a consumed path is declared as an external (non-step) input."""
    p = path.rstrip("/")
    for ext in external_inputs:
        e = ext.rstrip("/")
        if p == e or p.startswith(e + "/") or e == "external_providers":
            return True
    return False


@lru_cache(maxsize=1)
def compile_dag() -> dict[str, Any]:
    """Compile the registry into a validated DAG.

    Returns a dict with:
      - ``nodes``: list of active step ids
      - ``edges``: {consumer: [producers]} (same as _edges, in-place-refresh fixed)
      - ``topological_order``: Kahn-sorted step ids
      - ``cycles``: list of cycle node-sets (empty if acyclic)
      - ``missing_producers``: [{step, input}] for inputs with no producer and
        not in external_inputs
      - ``duplicate_writers``: [{path, steps}] for output paths declared by 2+
        steps (exact-path match)
      - ``decision_adjacent_cww``: step ids that are continue_with_warning AND
        transitively reach a decision-adjacent sink
      - ``sequence_contradictions``: [{step, producer, step_seq, producer_seq}]
        where a step runs before its declared producer in daily_run_sequence
      - ``valid``: bool, True iff cycles/missing_producers/duplicate_writers/
        decision_adjacent_cww/sequence_contradictions are all empty
    """
    from scripts._daily_run_sequence import load_daily_run_sequence

    reg = load_registry()
    steps = reg.get("steps", {})
    external_inputs = reg.get("external_inputs", []) or []
    edges = _edges()
    nodes = [sid for sid, s in steps.items() if s.get("status", "active") not in ("archived",)]

    # Cycle detection (Kahn).
    in_degree = {n: 0 for n in nodes}
    for cid, producers in edges.items():
        if cid in in_degree:
            in_degree[cid] = sum(1 for p in producers if p in in_degree)
    queue = [n for n in nodes if in_degree.get(n, 0) == 0]
    topo: list[str] = []
    while queue:
        n = queue.pop(0)
        topo.append(n)
        for cid, producers in edges.items():
            if n in producers and cid in in_degree:
                in_degree[cid] -= 1
                if in_degree[cid] == 0:
                    queue.append(cid)
    cycles = [n for n in nodes if in_degree.get(n, 0) > 0]

    # Missing producers: an input with no step-producer and not external.
    missing_producers: list[dict[str, str]] = []
    for sid, s in steps.items():
        if s.get("status", "active") in ("archived",):
            continue
        ins = [p.rstrip("/") for p in _contract_paths(s, "inputs") if p]
        producers = set(edges.get(sid, []))
        for inp in ins:
            if not producers and not _is_external_input(inp, external_inputs):
                # Check if ANY step produces this input.
                if not _has_producer(inp, steps):
                    missing_producers.append({"step": sid, "input": inp})
            elif not any(_path_produced_by(inp, p, steps) for p in producers):
                if not _is_external_input(inp, external_inputs):
                    missing_producers.append({"step": sid, "input": inp})

    # Duplicate writers (exact output path declared by 2+ active steps).
    path_to_steps: dict[str, list[str]] = {}
    for sid, s in steps.items():
        if s.get("status", "active") in ("archived",):
            continue
        for out in _contract_paths(s, "outputs"):
            p = out.rstrip("/")
            path_to_steps.setdefault(p, []).append(sid)
    duplicate_writers = [
        {"path": p, "steps": ss} for p, ss in path_to_steps.items() if len(ss) > 1
    ]

    # Decision-adjacent continue_with_warning: a CWW step that transitively
    # reaches a decision-adjacent sink.
    decision_adjacent_cww = _decision_adjacent_cww_steps(steps, edges)

    # Sequence contradictions: step runs before its producer in the sequence.
    sequence = load_daily_run_sequence()
    seq_index = {str(sm.get("id", "")): i for i, sm in enumerate(sequence)}
    sequence_contradictions: list[dict[str, Any]] = []
    for cid, producers in edges.items():
        if cid not in seq_index:
            continue
        for p in producers:
            if p in seq_index and seq_index[p] > seq_index[cid]:
                sequence_contradictions.append({
                    "step": cid, "producer": p,
                    "step_seq": seq_index[cid], "producer_seq": seq_index[p],
                })

    valid = (
        not cycles
        and not missing_producers
        and not duplicate_writers
        and not decision_adjacent_cww
        and not sequence_contradictions
    )
    return {
        "nodes": nodes,
        "edges": dict(edges),
        "topological_order": topo,
        "cycles": cycles,
        "missing_producers": missing_producers,
        "duplicate_writers": duplicate_writers,
        "decision_adjacent_cww": decision_adjacent_cww,
        "sequence_contradictions": sequence_contradictions,
        "valid": valid,
    }


def _has_producer(path: str, steps: dict[str, Any]) -> bool:
    """True if any active step declares an output overlapping ``path``."""
    p = path.rstrip("/")
    for sid, s in steps.items():
        if s.get("status", "active") in ("archived",):
            continue
        ins = {x.rstrip("/") for x in _contract_paths(s, "inputs") if x}
        for out in _contract_paths(s, "outputs"):
            o = out.rstrip("/")
            if o in ins:
                continue  # in-place mutator
            if p == o or p.startswith(o + "/") or o.startswith(p + "/"):
                return True
    return False


def _path_produced_by(path: str, producer: str, steps: dict[str, Any]) -> bool:
    """True if ``producer`` step declares an output overlapping ``path``."""
    s = steps.get(producer, {})
    ins = {x.rstrip("/") for x in _contract_paths(s, "inputs") if x}
    p = path.rstrip("/")
    for out in _contract_paths(s, "outputs"):
        o = out.rstrip("/")
        if o in ins:
            continue
        if p == o or p.startswith(o + "/"):
            return True
    return False


def _decision_adjacent_cww_steps(
    steps: dict[str, Any], edges: dict[str, list[str]]
) -> list[str]:
    """Steps with continue_with_warning that transitively reach a
    decision-adjacent sink.

    A decision-adjacent sink is a step that writes under the judgment /
    trade_decision / position / shadow trees, OR declares
    allowed_to_affect_core_judgment: true. Pure display artifacts under
    Output/current/ (e.g. current_status writing status.json) are NOT
    decision-adjacent - they are readouts, not decision inputs.
    """
    # Sinks = decision-adjacent writers.
    sinks: set[str] = set()
    for sid, s in steps.items():
        if s.get("allowed_to_affect_core_judgment") is True:
            sinks.add(sid)
            continue
        for out in _contract_paths(s, "outputs"):
            o = out.rstrip("/")
            # judgment / trade_decision / position / shadow trees are
            # decision-adjacent; Output/current/ display artifacts are not.
            if any(o.startswith(t.rstrip("/")) for t in _DECISION_ADJACENT_TREES
                   if not t.rstrip("/").endswith("current")):
                sinks.add(sid)
                break
    # Forward reachability: build forward edges (producer -> consumers).
    forward: dict[str, list[str]] = {}
    for cid, producers in edges.items():
        for p in producers:
            forward.setdefault(p, []).append(cid)
    # BFS from each CWW step; if it reaches a sink, it's a violation.
    violations: list[str] = []
    for sid, s in steps.items():
        if failure_behavior_of(sid) != "continue_with_warning":
            continue
        if sid in sinks:
            continue
        seen: set[str] = set()
        queue = [sid]
        reached_sink = False
        while queue:
            n = queue.pop(0)
            if n in seen:
                continue
            seen.add(n)
            if n in sinks and n != sid:
                reached_sink = True
                break
            queue.extend(forward.get(n, []))
        if reached_sink:
            violations.append(sid)
    return violations


# ── failure_behavior interpreter ─────────────────────────────────────────


def interpret_failure(
    step_id: str, results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Decide what the executor should do with ``step_id`` given prior results.

    Returns ``{action, blocked_by, behavior, degraded}`` where action is one of:
      - ``"block"``: mark blocked_upstream, do not run (a propagating upstream
        failed).
      - ``"run"``: proceed normally.
      - ``"run_degraded"``: proceed but tag the result degraded (hold_flat
        upstream or lower_claim_ceiling upstream). Phase B records the degraded
        flag; the step itself still runs and is responsible for emitting a
        degraded/hold-flat output.

    This replaces the Phase A ``failed_upstream_of`` boolean with per-behavior
    discrimination, so ``hold_flat`` and ``lower_claim_ceiling`` upstreams no
    longer hard-block a step that should degrade-and-continue.
    """
    status_by_step = {r.get("step"): r.get("status") for r in results}
    blocked_by: list[str] = []
    degraded_by: list[str] = []
    for up in upstream_of(step_id):
        st = status_by_step.get(up)
        if st is None or st == "success":
            continue
        up_fb = failure_behavior_of(up)
        if up_fb in ("block_current_readout", "block_core_judgment",
                     "block_promotion", "decision_adjacent_block"):
            blocked_by.append(up)
        elif up_fb == "hold_flat":
            # hold_flat upstream: degrade this step (let it emit a hold-flat
            # card), don't hard-block. trade_decision/risk_gate still produce
            # a (degraded) output rather than vanishing.
            degraded_by.append(up)
        elif up_fb == "lower_claim_ceiling":
            degraded_by.append(up)
        # continue_with_warning / research_only / unset: never propagate.
    if blocked_by:
        return {
            "action": "block",
            "blocked_by": blocked_by,
            "behavior": failure_behavior_of(step_id),
            "degraded": False,
        }
    if degraded_by:
        return {
            "action": "run_degraded",
            "blocked_by": [],
            "behavior": failure_behavior_of(step_id),
            "degraded": True,
            "degraded_by": degraded_by,
        }
    return {
        "action": "run",
        "blocked_by": [],
        "behavior": failure_behavior_of(step_id),
        "degraded": False,
    }
