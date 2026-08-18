from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, cast

import numpy as np

from src.core.interfaces import ODEEngineInterface
from src.core.models import ProxyReading
from src.core.representation.state_space_mapping import DefaultStateSpaceMapping, StateSpaceMapping
from src.mechanisms.base import MechanismRegistry
from src.operators.operator_schema import OperatorDiagnostics


@dataclass(frozen=True)
class ODESolverDiagnostics:
    backend: str
    solver: str
    steps: int
    final_time: float
    threshold_hit_time: float | None = None
    spectral_abscissa: float | None = None
    jacobian_frobenius_norm: float | None = None
    spectral_abscissa_drift: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "solver": self.solver,
            "steps": self.steps,
            "final_time": self.final_time,
            "threshold_hit_time": self.threshold_hit_time,
            "spectral_abscissa": self.spectral_abscissa,
            "jacobian_frobenius_norm": self.jacobian_frobenius_norm,
            "spectral_abscissa_drift": self.spectral_abscissa_drift,
        }


@dataclass
class DiffraxODEEngine(ODEEngineInterface):
    """
    Adaptive ODE backend for the structural state evolution layer.

    Diffrax/JAX are optional runtime dependencies. When they are unavailable,
    this class falls back to SciPy and finally to a dependency-light RK4 path
    while preserving the same public interface.
    """

    mechanism_registry: MechanismRegistry | None = None
    state_space_mapping: StateSpaceMapping = field(default_factory=DefaultStateSpaceMapping)
    preferred_backend: str = "auto"
    default_solver: str = "tsit5"
    rtol: float = 1e-5
    atol: float = 1e-7
    last_diagnostics: ODESolverDiagnostics | None = None

    def integrate(
        self,
        proxy: ProxyReading,
        params: dict,
        operator_hints: OperatorDiagnostics | None = None,
    ) -> np.ndarray:
        try:
            clean_params = dict(params or {})
            mechanism_context = clean_params.get("mechanism_context", {})
            skip_mechanisms = bool(clean_params.get("skip_mechanism_shift", False))
            effective_proxy = (
                self.mechanism_registry.shifted_proxy(proxy, mechanism_context)
                if self.mechanism_registry is not None and not skip_mechanisms
                else proxy
            )
            z0 = self.map_proxy_to_initial_state(effective_proxy)
            horizon = float(clean_params.get("horizon", 4.0))
            dt = float(clean_params.get("dt", 1.0))
            alpha = float(clean_params.get("alpha", 0.1))
            beta = float(clean_params.get("beta", 0.05))
            if horizon <= 0 or dt <= 0:
                raise ValueError("horizon and dt must be positive")
            alpha, beta = self._apply_operator_hints(alpha, beta, operator_hints)

            backend = str(clean_params.get("backend", self.preferred_backend)).lower()
            solver = str(clean_params.get("solver", self.default_solver)).lower()
            if backend in {"auto", "jax", "diffrax"}:
                try:
                    z, diagnostics = self._solve_diffrax(
                        z0=z0,
                        horizon=horizon,
                        dt=dt,
                        alpha=alpha,
                        beta=beta,
                        solver_name=solver,
                        params=clean_params,
                    )
                    self.last_diagnostics = diagnostics
                    return cast(np.ndarray, np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0))
                except (ValueError, RuntimeError, ImportError):
                    if backend in {"jax", "diffrax"}:
                        raise

            z, diagnostics = self._solve_scipy_or_rk4(
                z0=z0,
                horizon=horizon,
                dt=dt,
                alpha=alpha,
                beta=beta,
                solver_name="rk45",
                params=clean_params,
            )
            self.last_diagnostics = diagnostics
            return cast(np.ndarray, np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0))
        except (ValueError, RuntimeError, ImportError, OverflowError):
            import logging

            logging.getLogger(__name__).warning(
                "ODE integration failed all backends; returning zero state.",
                exc_info=True,
            )
            self.last_diagnostics = ODESolverDiagnostics(
                backend="failed",
                solver="none",
                steps=0,
                final_time=0.0,
            )
            return cast(np.ndarray, np.zeros(6, dtype=float))

    def map_proxy_to_initial_state(self, proxy: ProxyReading) -> np.ndarray:
        return cast(np.ndarray, self.state_space_mapping.map_proxy(proxy).as_array())

    def curvature_diagnostics(
        self,
        state: np.ndarray,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, float | None]:
        params = dict(params or {})
        alpha = float(params.get("alpha", 0.1))
        beta = float(params.get("beta", 0.05))
        jac = self._jacobian(np.asarray(state, dtype=float), alpha=alpha, beta=beta)
        return _jacobian_metrics(jac)

    def _apply_operator_hints(
        self,
        alpha: float,
        beta: float,
        operator_hints: OperatorDiagnostics | None,
    ) -> tuple[float, float]:
        if operator_hints is None:
            return alpha, beta
        alpha = alpha * max(0.3, float(operator_hints.compression_ratio))
        beta = beta * (1.0 + max(0.0, float(operator_hints.shadow_transfer)))
        return alpha, beta

    def _drift_numpy(self, _t: float, z: np.ndarray, alpha: float, beta: float) -> np.ndarray:
        dz = np.zeros_like(z, dtype=float)
        dz[0] = alpha * (z[2] - z[0]) + beta * z[5]
        dz[1] = alpha * (z[3] - z[1]) + beta * z[4]
        dz[2] = -alpha * z[2] + beta * abs(z[0])
        dz[3] = -alpha * z[3] + beta * abs(z[1])
        dz[4] = alpha * (z[0] - z[4]) + beta * z[2]
        dz[5] = alpha * (z[1] - z[5]) + beta * z[3]
        return cast(np.ndarray, dz)

    def _solve_diffrax(
        self,
        z0: np.ndarray,
        horizon: float,
        dt: float,
        alpha: float,
        beta: float,
        solver_name: str,
        params: Mapping[str, Any],
    ) -> tuple[np.ndarray, ODESolverDiagnostics]:
        import jax  # type: ignore
        import diffrax  # type: ignore
        import jax.numpy as jnp  # type: ignore

        jax.config.update("jax_enable_x64", True)

        def vf(t, y, args):
            a, b = args
            return jnp.array(
                [
                    a * (y[2] - y[0]) + b * y[5],
                    a * (y[3] - y[1]) + b * y[4],
                    -a * y[2] + b * jnp.abs(y[0]),
                    -a * y[3] + b * jnp.abs(y[1]),
                    a * (y[0] - y[4]) + b * y[2],
                    a * (y[1] - y[5]) + b * y[3],
                ],
                dtype=y.dtype,
            )

        solver = _diffrax_solver(diffrax, solver_name)
        save_count = max(2, int(np.ceil(horizon / dt)) + 1)
        save_ts = np.linspace(0.0, horizon, save_count)
        sol = diffrax.diffeqsolve(
            diffrax.ODETerm(vf),
            solver,
            t0=0.0,
            t1=float(horizon),
            dt0=float(min(dt, horizon)),
            y0=jnp.asarray(z0, dtype=jnp.float64),
            args=(float(alpha), float(beta)),
            saveat=diffrax.SaveAt(ts=jnp.asarray(save_ts), dense=bool(params.get("dense", True))),
            stepsize_controller=diffrax.PIDController(rtol=self.rtol, atol=self.atol),
            max_steps=int(params.get("max_steps", 4096)),
        )
        ys = np.asarray(sol.ys, dtype=float)
        final = np.asarray(ys[-1], dtype=float)
        hit_time = threshold_crossing_time(
            times=save_ts,
            states=ys,
            dof_threshold=float(params.get("singular_dof_threshold", -0.65)),
            curvature_threshold=float(params.get("singular_curvature_threshold", 0.65)),
            shadow_threshold=float(params.get("singular_shadow_threshold", 0.65)),
        )
        jac0 = self._jacobian(np.asarray(z0, dtype=float), alpha=alpha, beta=beta)
        jac1 = self._jacobian(final, alpha=alpha, beta=beta)
        metrics = _jacobian_metrics(jac1)
        diagnostics = ODESolverDiagnostics(
            backend="diffrax",
            solver=solver.__class__.__name__,
            steps=int(len(ys)),
            final_time=float(horizon),
            threshold_hit_time=hit_time,
            spectral_abscissa=metrics["spectral_abscissa"],
            jacobian_frobenius_norm=metrics["jacobian_frobenius_norm"],
            spectral_abscissa_drift=_spectral_abscissa(jac1) - _spectral_abscissa(jac0),
        )
        return final, diagnostics

    def _solve_scipy_or_rk4(
        self,
        z0: np.ndarray,
        horizon: float,
        dt: float,
        alpha: float,
        beta: float,
        solver_name: str,
        params: Mapping[str, Any],
    ) -> tuple[np.ndarray, ODESolverDiagnostics]:
        try:
            from scipy.integrate import solve_ivp  # type: ignore

            sol = solve_ivp(
                lambda t, z: self._drift_numpy(t, z, alpha=alpha, beta=beta),
                t_span=(0.0, horizon),
                y0=z0,
                method="RK45",
                max_step=dt,
                rtol=float(params.get("rtol", self.rtol)),
                atol=float(params.get("atol", self.atol)),
            )
            if sol.success and sol.y.shape[1] > 0:
                final = np.asarray(sol.y[:, -1], dtype=float)
                states = np.asarray(sol.y.T, dtype=float)
                times = np.asarray(sol.t, dtype=float)
                jac0 = self._jacobian(np.asarray(z0, dtype=float), alpha=alpha, beta=beta)
                jac1 = self._jacobian(final, alpha=alpha, beta=beta)
                metrics = _jacobian_metrics(jac1)
                return final, ODESolverDiagnostics(
                    backend="scipy",
                    solver=solver_name,
                    steps=int(sol.y.shape[1]),
                    final_time=float(sol.t[-1]),
                    threshold_hit_time=threshold_crossing_time(
                        times=times,
                        states=states,
                        dof_threshold=float(params.get("singular_dof_threshold", -0.65)),
                        curvature_threshold=float(params.get("singular_curvature_threshold", 0.65)),
                        shadow_threshold=float(params.get("singular_shadow_threshold", 0.65)),
                    ),
                    spectral_abscissa=metrics["spectral_abscissa"],
                    jacobian_frobenius_norm=metrics["jacobian_frobenius_norm"],
                    spectral_abscissa_drift=_spectral_abscissa(jac1) - _spectral_abscissa(jac0),
                )
        except (ImportError, RuntimeError, ValueError) as exc:
            logging.getLogger(__name__).info(
                "SciPy solve_ivp unavailable (%s); falling back to RK4.", exc
            )

        times, states = self._solve_rk4(z0, horizon=horizon, dt=dt, alpha=alpha, beta=beta)
        final = states[-1]
        jac0 = self._jacobian(np.asarray(z0, dtype=float), alpha=alpha, beta=beta)
        jac1 = self._jacobian(final, alpha=alpha, beta=beta)
        metrics = _jacobian_metrics(jac1)
        return final, ODESolverDiagnostics(
            backend="rk4",
            solver="fixed_step_rk4",
            steps=int(len(times)),
            final_time=float(times[-1]),
            threshold_hit_time=threshold_crossing_time(
                times=times,
                states=states,
                dof_threshold=float(params.get("singular_dof_threshold", -0.65)),
                curvature_threshold=float(params.get("singular_curvature_threshold", 0.65)),
                shadow_threshold=float(params.get("singular_shadow_threshold", 0.65)),
            ),
            spectral_abscissa=metrics["spectral_abscissa"],
            jacobian_frobenius_norm=metrics["jacobian_frobenius_norm"],
            spectral_abscissa_drift=_spectral_abscissa(jac1) - _spectral_abscissa(jac0),
        )

    def _solve_rk4(
        self,
        z0: np.ndarray,
        horizon: float,
        dt: float,
        alpha: float,
        beta: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        steps = max(1, int(np.ceil(horizon / dt)))
        times = np.linspace(0.0, horizon, steps + 1)
        states: np.ndarray = np.zeros((steps + 1, len(z0)), dtype=float)
        states[0] = z0
        for idx in range(steps):
            t = float(times[idx])
            h = float(times[idx + 1] - times[idx])
            z = states[idx]
            k1 = self._drift_numpy(t, z, alpha=alpha, beta=beta)
            k2 = self._drift_numpy(t + h / 2.0, z + h * k1 / 2.0, alpha=alpha, beta=beta)
            k3 = self._drift_numpy(t + h / 2.0, z + h * k2 / 2.0, alpha=alpha, beta=beta)
            k4 = self._drift_numpy(t + h, z + h * k3, alpha=alpha, beta=beta)
            states[idx + 1] = z + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        return times, states

    def _jacobian(self, state: np.ndarray, alpha: float, beta: float) -> np.ndarray:
        try:
            import jax  # type: ignore
            import jax.numpy as jnp  # type: ignore

            jax.config.update("jax_enable_x64", True)

            def f(y):
                return jnp.asarray(self._drift_jax(y, alpha=alpha, beta=beta))

            return cast(np.ndarray, np.asarray(jax.jacfwd(f)(jnp.asarray(state, dtype=jnp.float64)), dtype=float))
        except (ImportError, RuntimeError) as exc:
            import logging

            logging.getLogger(__name__).info("JAX Jacobian unavailable (%s); falling back to finite difference.", exc)
            return self._jacobian_finite_difference(state, alpha=alpha, beta=beta)

    def _drift_jax(self, y: Any, alpha: float, beta: float) -> Any:
        import jax.numpy as jnp  # type: ignore

        return jnp.array(
            [
                alpha * (y[2] - y[0]) + beta * y[5],
                alpha * (y[3] - y[1]) + beta * y[4],
                -alpha * y[2] + beta * jnp.abs(y[0]),
                -alpha * y[3] + beta * jnp.abs(y[1]),
                alpha * (y[0] - y[4]) + beta * y[2],
                alpha * (y[1] - y[5]) + beta * y[3],
            ],
            dtype=y.dtype,
        )

    def _jacobian_finite_difference(self, state: np.ndarray, alpha: float, beta: float) -> np.ndarray:
        eps = 1e-5
        base = np.asarray(state, dtype=float)
        jac: np.ndarray = np.zeros((len(base), len(base)), dtype=float)
        for idx in range(len(base)):
            step = np.zeros_like(base)
            step[idx] = eps
            fp = self._drift_numpy(0.0, base + step, alpha=alpha, beta=beta)
            fm = self._drift_numpy(0.0, base - step, alpha=alpha, beta=beta)
            jac[:, idx] = (fp - fm) / (2.0 * eps)
        return cast(np.ndarray, jac)


def threshold_crossing_time(
    times: np.ndarray,
    states: np.ndarray,
    dof_threshold: float,
    curvature_threshold: float,
    shadow_threshold: float,
) -> float | None:
    if states.ndim != 2 or states.shape[1] < 6:
        return None
    # State-space mapping labels: M_obs, M_latent, D_obs, D_latent, K_mode, X_mode.
    dof = states[:, 2]
    curvature = states[:, 4]
    shadow = states[:, 5]
    hits = np.where((dof <= dof_threshold) & (curvature >= curvature_threshold) & (shadow >= shadow_threshold))[0]
    if hits.size == 0:
        return None
    return float(times[int(hits[0])])


def _diffrax_solver(diffrax: Any, solver_name: str) -> Any:
    key = solver_name.strip().lower()
    if key == "kvaerno5":
        return diffrax.Kvaerno5()
    if key == "dopri8":
        return diffrax.Dopri8()
    if key == "dopri5":
        return diffrax.Dopri5()
    return diffrax.Tsit5()


def _jacobian_metrics(jacobian: np.ndarray) -> dict[str, float | None]:
    if jacobian.size == 0 or not np.isfinite(jacobian).all():
        return {
            "spectral_abscissa": None,
            "jacobian_frobenius_norm": None,
        }
    return {
        "spectral_abscissa": _spectral_abscissa(jacobian),
        "jacobian_frobenius_norm": float(np.linalg.norm(jacobian, ord="fro")),
    }


def _spectral_abscissa(jacobian: np.ndarray) -> float:
    vals = np.linalg.eigvals(jacobian)
    return float(np.max(np.real(vals)))
