from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.simulation.agent_based_lab import AgentBasedLab, ScenarioSummary, ToyABMScenario


@dataclass(frozen=True)
class CrisisCaseResult:
    name: str
    mechanism_chain: str
    scenario: ToyABMScenario
    summary: ScenarioSummary
    terminal_state: dict[str, float | int | bool]


CRISIS_CASES: dict[str, tuple[str, ToyABMScenario]] = {
    "subprime_2008": (
        "housing collateral shock -> funding haircut pressure -> dealer/intermediary capacity contraction -> forced shadow realization",
        ToyABMScenario(
            steps=104,
            seed=2008,
            initial_leverage=7.0,
            target_leverage=8.0,
            leverage_adjustment_speed=0.22,
            funding_stress=0.78,
            collateral_shock=0.34,
            network_concentration=0.82,
            dealer_capacity=0.55,
            policy_delay=18,
            policy_backstop_strength=0.38,
            shadow_accumulation_speed=0.45,
        ),
    ),
    "cdo_tranching": (
        "structured-credit opacity -> tranche verifiability gap -> nonlinear correlation/default mapping -> shadow-load release",
        ToyABMScenario(
            steps=78,
            seed=2007,
            initial_leverage=6.2,
            target_leverage=7.5,
            leverage_adjustment_speed=0.18,
            funding_stress=0.68,
            collateral_shock=0.28,
            network_concentration=0.9,
            dealer_capacity=0.62,
            policy_delay=16,
            policy_backstop_strength=0.3,
            shadow_accumulation_speed=0.5,
        ),
    ),
    "ltcm_1998": (
        "convergence leverage -> correlation breakdown -> dealer capacity bottleneck -> coordinated backstop",
        ToyABMScenario(
            steps=52,
            seed=1998,
            initial_leverage=12.0,
            target_leverage=14.0,
            leverage_adjustment_speed=0.35,
            funding_stress=0.58,
            collateral_shock=0.18,
            network_concentration=0.88,
            dealer_capacity=0.48,
            policy_delay=6,
            policy_backstop_strength=0.42,
            shadow_accumulation_speed=0.32,
        ),
    ),
}


def run_crisis_case(name: str, lab: AgentBasedLab | None = None) -> CrisisCaseResult:
    if name not in CRISIS_CASES:
        known = ", ".join(sorted(CRISIS_CASES))
        raise KeyError(f"Unknown crisis case {name!r}. Known cases: {known}")
    mechanism_chain, scenario = CRISIS_CASES[name]
    runner = lab or AgentBasedLab()
    frame = runner.simulate(scenario)
    summary = runner.summarize(frame)
    terminal_state = _terminal_state(frame)
    return CrisisCaseResult(
        name=name,
        mechanism_chain=mechanism_chain,
        scenario=scenario,
        summary=summary,
        terminal_state=terminal_state,
    )


def run_crisis_cases(names: list[str] | None = None) -> pd.DataFrame:
    selected = names or list(CRISIS_CASES)
    rows: list[dict[str, object]] = []
    for name in selected:
        result = run_crisis_case(name)
        row = {
            "case": result.name,
            "mechanism_chain": result.mechanism_chain,
            "regime": classify_case_regime(result.summary),
            "singular_probability": result.summary.singular_probability,
            "first_singular_step": result.summary.first_singular_step,
            "max_sigma": result.summary.max_sigma,
            "min_d": result.summary.min_d,
            "max_k": result.summary.max_k,
            "max_x": result.summary.max_x,
        }
        row.update({f"terminal_{key}": value for key, value in result.terminal_state.items()})
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def classify_case_regime(summary: ScenarioSummary) -> str:
    if summary.singular_probability > 0.25:
        return "STRUCTURAL_SINGULAR_REGIME"
    if summary.singular_probability > 0.0:
        return "TRANSIENT_SINGULAR_CONTACT"
    if summary.max_sigma >= 2.0:
        return "LOCAL_INSTABILITY"
    return "STABLE_LOCAL"


def case_parameters() -> pd.DataFrame:
    rows = []
    for name, (_, scenario) in CRISIS_CASES.items():
        row = {"case": name}
        row.update(asdict(scenario))
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def _terminal_state(frame: pd.DataFrame) -> dict[str, float | int | bool]:
    if frame.empty:
        return {}
    row = frame.iloc[-1]
    keys = ["step", "M", "D", "K", "X", "Sigma", "leverage", "collateral_value", "dealer_capacity", "hidden_load", "singular_flag"]
    out: dict[str, float | int | bool] = {}
    for key in keys:
        value = row[key]
        if key == "singular_flag":
            out[key] = bool(value)
        elif key == "step":
            out[key] = int(value)
        else:
            out[key] = float(value)
    return out
