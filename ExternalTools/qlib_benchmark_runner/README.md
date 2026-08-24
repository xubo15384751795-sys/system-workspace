# Qlib Benchmark Runner
#
# Isolated external executor for market feedback benchmarks.
# This runner is NOT part of the main system. It communicates only through
# file interfaces (job spec JSON, sandbox input, output directories).
#
# See: Output/benchmarks/market_feedback/ for benchmark run directories.
# See: packages/workbench/src/benchmarks/market_feedback/ for the orchestration layer.

## Governed Experiment Protocol

When a `qlib_job_spec.json` contains an embedded `experiment_spec`, it is the
engine-neutral declaration of the research question, hypothesis, dataset,
models, evaluation, and governance boundary. The runner may execute that
specification, but it must not write Judgment, Current State, or publication
artifacts.

The Workbench wraps `qlib_output/raw_metrics.json` as the evidence-only
`experiment_result.json`. A blocked or inconclusive executor result remains
inconclusive and cannot pass the benchmark gate or enter the Learning Hub.
Existing job specs without `experiment_spec` remain supported during the
transition.
