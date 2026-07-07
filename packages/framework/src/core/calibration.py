from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FrozenThresholds:
    sigma: float
    joint_hitting_enabled: bool = True
    dof_collapse: float = -0.65
    curvature_spike: float = 0.65
    forced_realization: float = 0.65
    calibration_mode: str = "fixed_config"
    training_window: tuple[str, str] | None = None
    evaluation_window: tuple[str, str] | None = None
    frozen: bool = True


@dataclass(frozen=True)
class FrozenProxyWeights:
    M: float
    D: float
    K: float
    X: float


def build_thresholds(config: dict[str, Any]) -> FrozenThresholds:
    payload = config.get("thresholds", {})
    payload = payload if isinstance(payload, dict) else {}
    joint = payload.get("joint_hitting", {})
    joint = joint if isinstance(joint, dict) else {}
    protocol = payload.get("protocol", {})
    protocol = protocol if isinstance(protocol, dict) else {}
    return FrozenThresholds(
        sigma=float(payload.get("sigma", 2.0)),
        joint_hitting_enabled=bool(joint.get("enabled", True)),
        dof_collapse=float(joint.get("dof_collapse", -0.65)),
        curvature_spike=float(joint.get("curvature_spike", 0.65)),
        forced_realization=float(joint.get("forced_realization", 0.65)),
        calibration_mode=str(protocol.get("calibration_mode", "fixed_config")),
        training_window=_window(protocol.get("training_window")),
        evaluation_window=_window(protocol.get("evaluation_window")),
        frozen=bool(protocol.get("frozen", True)),
    )


def build_proxy_weights(config: dict[str, Any]) -> FrozenProxyWeights:
    payload = config.get("proxies", {}).get("weights", {})
    return FrozenProxyWeights(
        M=float(payload.get("M", 0.25)),
        D=float(payload.get("D", 0.25)),
        K=float(payload.get("K", 0.25)),
        X=float(payload.get("X", 0.25)),
    )


def _window(value: Any) -> tuple[str, str] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (str(value[0]), str(value[1]))
    if isinstance(value, dict):
        start = value.get("start")
        end = value.get("end")
        if start is not None and end is not None:
            return (str(start), str(end))
    return None
