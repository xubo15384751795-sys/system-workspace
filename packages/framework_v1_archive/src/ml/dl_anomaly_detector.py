from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

from src.core.interfaces import AnomalyDetectorInterface, SnapshotStoreInterface
from src.core.models import ProxyReading
from src.ml.ml_anomaly import IsolationForestDetector, _proxy_to_vec, _snapshots_to_matrix
from src.ml.model_registry import ModelRegistry, ModelRegistryError


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def _snapshot_store_provenance(store: SnapshotStoreInterface) -> dict[str, Any]:
    """Return manifest-safe provenance for the store used during training.

    The runtime selects the canonical snapshot backend from configuration.  A
    hard-coded DuckDB label in a model manifest would therefore describe a
    different data path than the one actually used for training.  Keep the
    provenance structural and deterministic: backend identity, concrete store
    class, and any store paths exposed by the implementation.
    """

    class_name = type(store).__name__
    backend_by_class = {
        "HarvesterSnapshotStore": "harvester_parquet",
        "DuckDBSnapshotStore": "duckdb_legacy_readonly",
        "DualWriteSnapshotStore": "dual_write_harvester_primary",
    }
    paths: list[str] = []
    stores: list[SnapshotStoreInterface] = [store]
    seen: set[int] = set()
    while stores:
        current = stores.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        for attr in ("root", "path"):
            value = getattr(current, attr, None)
            if value is not None:
                rendered = str(value)
                if rendered not in paths:
                    paths.append(rendered)
        for attr in ("primary", "secondary"):
            nested = getattr(current, attr, None)
            if nested is not None and (
                hasattr(nested, "load_range") or hasattr(nested, "root") or hasattr(nested, "path")
            ):
                stores.append(nested)

    return {
        "training_data_source": "snapshot_store_interface",
        "training_data_backend": backend_by_class.get(class_name, class_name),
        "training_data_store_class": class_name,
        "training_data_paths": paths,
    }


@dataclass
class LSTMAutoencoderDetector(AnomalyDetectorInterface):
    """Window autoencoder anomaly score (LSTM when torch is available).

    Trains on historical snapshots from ``fit_from_history`` when torch is present;
    otherwise falls back to a stateful :class:`IsolationForestDetector`.
    Higher score ⇒ more anomalous.
    """

    window: int = 60
    hidden: int = 32
    epochs: int = 40
    lr: float = 1e-2
    threshold_sigma: float = 2.5
    min_train_sequences: int = 32
    _snapshot_store: SnapshotStoreInterface | None = field(default=None, repr=False)
    _fallback: IsolationForestDetector | None = field(default=None, repr=False)
    _torch: Any = field(default=None, repr=False)
    _model: Any = field(default=None, repr=False)
    _mean: np.ndarray | None = field(default=None, repr=False)
    _std: np.ndarray | None = field(default=None, repr=False)
    _train_errors: np.ndarray | None = field(default=None, repr=False)
    _manifest: dict[str, Any] = field(default_factory=dict, repr=False)

    def bind_snapshot_store(self, store: SnapshotStoreInterface) -> None:
        self._snapshot_store = store

    @classmethod
    def load(cls, model_release: str = "latest", *, config: dict[str, Any]) -> LSTMAutoencoderDetector:
        reg = ModelRegistry.from_config(config)
        det = cls()
        try:
            man = reg.load_manifest("anomaly", model_release)
            reg.assert_constitution_cleared(man)
            wpath = reg.weights_path("anomaly", model_release)
            if _torch_available() and wpath.exists():
                import torch  # type: ignore
                from torch import nn

                class _LstmAE(nn.Module):
                    def __init__(self, n_features: int = 4, hidden_size: int = 32) -> None:
                        super().__init__()
                        self.enc = nn.LSTM(n_features, hidden_size, batch_first=True)
                        self.dec = nn.LSTM(hidden_size, n_features, batch_first=True)

                    def forward(self, x: torch.Tensor) -> torch.Tensor:
                        enc_out, (h, _) = self.enc(x)
                        h_last = h[-1].unsqueeze(1).expand(-1, x.size(1), -1)
                        y, _ = self.dec(h_last)
                        return y

                det._torch = torch
                hidden = int(man.get("hidden", det.hidden))
                det._model = _LstmAE(hidden_size=hidden)
                try:
                    state_dict = torch.load(wpath, map_location="cpu", weights_only=True)
                except TypeError:
                    state_dict = torch.load(wpath, map_location="cpu")
                det._model.load_state_dict(state_dict)
                det._model.eval()
                det._mean = np.array(man.get("norm_mean", [0.0, 0.0, 0.0, 0.0]), dtype=np.float64)
                det._std = np.array(man.get("norm_std", [1.0, 1.0, 1.0, 1.0]), dtype=np.float64)
                stats = man.get("train_error_stats") or {}
                mu = float(stats.get("mean", 0.0))
                sd = float(stats.get("std", 1.0)) or 1.0
                det._train_errors = np.array([mu, sd], dtype=np.float64)
                det._manifest = man
        except (ModelRegistryError, OSError, ValueError, RuntimeError, TypeError):
            det._model = None
        return det

    def fit_from_history(self, snapshot_store: SnapshotStoreInterface, start: str, end: str) -> None:
        self._fallback = IsolationForestDetector(
            contamination=0.05,
            random_state=7,
            min_samples=10,
        )
        self._fallback.fit_from_history(snapshot_store, start, end)
        self.bind_snapshot_store(snapshot_store)

        snaps = snapshot_store.load_range(start, end)
        mat = _snapshots_to_matrix(snaps)
        if mat.shape[0] < self.window + 5 or not _torch_available():
            self._model = None
            return

        seqs = self._build_sequences(mat, self.window)
        if seqs.shape[0] < self.min_train_sequences:
            self._model = None
            return

        mean = seqs.mean(axis=(0, 1))
        std = seqs.std(axis=(0, 1)) + 1e-6
        norm = (seqs - mean) / std

        import torch  # type: ignore
        from torch import nn

        class _LstmAE(nn.Module):
            def __init__(self, n_features: int = 4, hidden_size: int = 32) -> None:
                super().__init__()
                self.enc = nn.LSTM(n_features, hidden_size, batch_first=True)
                self.dec = nn.LSTM(hidden_size, n_features, batch_first=True)

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                enc_out, (h, _) = self.enc(x)
                h_last = h[-1].unsqueeze(1).expand(-1, x.size(1), -1)
                y, _ = self.dec(h_last)
                return y

        xb = torch.tensor(norm, dtype=torch.float32)
        model = _LstmAE(hidden_size=self.hidden)
        opt = torch.optim.Adam(model.parameters(), lr=self.lr)
        loss_fn = nn.MSELoss()
        model.train()
        for _ in range(self.epochs):
            opt.zero_grad()
            yhat = model(xb)
            loss = loss_fn(yhat, xb)
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            err = torch.mean((model(xb) - xb) ** 2, dim=(1, 2)).numpy()
        self._mean = mean
        self._std = std
        self._train_errors = np.array([float(err.mean()), float(err.std() + 1e-9)], dtype=np.float64)
        self._torch = torch
        self._model = model

    def _build_sequences(self, mat: np.ndarray, window: int) -> np.ndarray:
        out: list[np.ndarray] = []
        for i in range(0, mat.shape[0] - window + 1):
            out.append(mat[i : i + window])
        if not out:
            return cast(np.ndarray, np.zeros((0, window, 4), dtype=np.float64))
        return cast(np.ndarray, np.stack(out, axis=0))

    def _latest_window(self, run_date: str) -> np.ndarray | None:
        if self._snapshot_store is None:
            return None
        snaps = self._snapshot_store.load_range("1900-01-01", run_date)
        prior = [s for s in snaps if s.run_date <= run_date]
        if len(prior) < self.window:
            return None
        tail = prior[-self.window :]
        return cast(np.ndarray, _snapshots_to_matrix(tail))

    def score(self, proxy: ProxyReading) -> float:
        if self._model is not None and self._mean is not None and self._std is not None and self._train_errors is not None:
            win = self._latest_window(proxy.run_date)
            if win is not None and win.shape[0] == self.window:
                norm = (win - self._mean) / self._std
                t = self._torch.tensor(norm.reshape(1, self.window, 4), dtype=self._torch.float32)
                self._model.eval()
                with self._torch.no_grad():
                    yhat = self._model(t)
                    mse = float(self._torch.mean((yhat - t) ** 2).item())
                mu, sd = float(self._train_errors[0]), float(self._train_errors[1])
                z = abs(mse - mu) / sd
                return float(z)
        if self._fallback is not None:
            return float(self._fallback.score(proxy))
        return float(np.mean(np.abs(_proxy_to_vec(proxy))))

    @classmethod
    def train_and_save(
        cls,
        snapshot_store: SnapshotStoreInterface,
        output_root: Path,
        source_release: str,
        *,
        start: str = "2015-01-01",
        end: str = "9999-12-31",
        window: int = 60,
        hidden: int = 32,
    ) -> Path:
        """Fit on snapshot history and write ``model.pt`` + ``training_manifest.json``."""
        import io

        tmp = cls(window=window, hidden=hidden)
        tmp.fit_from_history(snapshot_store, start, end)
        if tmp._model is None or tmp._mean is None or tmp._std is None or tmp._train_errors is None:
            raise RuntimeError("Insufficient data or torch missing; cannot train LSTM autoencoder.")

        import torch  # type: ignore

        buf = io.BytesIO()
        torch.save(tmp._model.state_dict(), buf)
        snaps = snapshot_store.load_range(start, end)
        data_provenance = _snapshot_store_provenance(snapshot_store)
        manifest = {
            "schema_version": "workbench.dl_model.v1",
            "model_type": "lstm_autoencoder_anomaly",
            "trained_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            **data_provenance,
            "source_releases_excluded": [],
            "training_rows": len(snaps),
            "window": window,
            "hidden": hidden,
            "norm_mean": tmp._mean.tolist(),
            "norm_std": tmp._std.tolist(),
            "train_error_stats": {
                "mean": float(tmp._train_errors[0]),
                "std": float(tmp._train_errors[1]),
            },
            "notes": "Training data from snapshot history only; no deformation run labels.",
        }
        reg = ModelRegistry(root=Path(output_root))
        reg.register("anomaly", source_release, weights_bytes=buf.getvalue(), manifest=manifest)
        return cast(Path, reg.manifest_path("anomaly", source_release))
