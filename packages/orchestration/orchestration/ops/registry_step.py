"""Generic Dagster op that runs the full registry sequence once.

Step order and commands stay in governance YAML; this op only schedules them.
"""
from __future__ import annotations

from dagster import op

from orchestration.sequence_executor import DailyRunContext, execute_daily_sequence


@op(name="execute_registry_sequence")
def execute_registry_sequence_op(context, payload):
    """Execute the compiled daily sequence with flags from ``payload``."""
    run_step_fn = payload["run_step_fn"]
    record_fn = payload["record_fn"]
    ctx = DailyRunContext(
        args=payload["args"],
        start_time=payload["start_time"],
        total_steps=int(payload["total_steps"]),
        run_step_fn=run_step_fn,
        record_fn=record_fn,
        benchmark_panel_path=payload["benchmark_panel_path"],
        run_id=str(payload.get("run_id") or ""),
    )
    results = execute_daily_sequence(ctx)
    context.log.info("Registry sequence finished with %d step results", len(results))
    return {"results": results, "run_id": ctx.run_id}
