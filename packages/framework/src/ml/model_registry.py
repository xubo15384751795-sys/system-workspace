from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ModelRegistryError(RuntimeError):
    pass


def resolve_ml_models_root(config: dict[str, Any]) -> Path:
    from src.core.runtime_context import RuntimePaths

    paths = config.get("paths")
    if isinstance(paths, dict):
        raw = paths.get("ml_models_root")
        if raw:
            path = Path(str(raw)).expanduser()
            if path.is_absolute():
                return path
            return RuntimePaths.discover().project_root / path
    out = config.get("output")
    if isinstance(out, dict) and out.get("dir"):
        return Path(str(out["dir"])).expanduser() / "ml_models"
    return RuntimePaths.discover().output_root / "ml_models"


def _resolve_release_dir(root: Path, model_release: str) -> Path:
    if model_release != "latest":
        p = root / model_release
        if not p.exists():
            raise ModelRegistryError(f"Missing release directory: {p}")
        return p.resolve()
    link = root / "latest"
    if link.is_symlink():
        target = link.readlink()
        return (target if target.is_absolute() else (link.parent / target)).resolve()
    if link.is_dir():
        return link.resolve()
    raise ModelRegistryError("No ml_models/latest symlink or directory found.")


@dataclass
class ModelRegistry:
    """Load Deformation DL weights under ``Output/ml_models/<release_id>/``."""

    root: Path
    _manifest_cache: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict, repr=False)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ModelRegistry:
        return cls(root=resolve_ml_models_root(config))

    def _model_dir(self, model_type: str, model_release: str) -> Path:
        base = _resolve_release_dir(self.root, model_release)
        return base / model_type

    def manifest_path(self, model_type: str, model_release: str) -> Path:
        return self._model_dir(model_type, model_release) / "training_manifest.json"

    def weights_path(self, model_type: str, model_release: str) -> Path:
        return self._model_dir(model_type, model_release) / "model.pt"

    def load_manifest(self, model_type: str, model_release: str = "latest") -> dict[str, Any]:
        key = (model_type, model_release)
        if key in self._manifest_cache:
            return dict(self._manifest_cache[key])
        path = self.manifest_path(model_type, model_release)
        if not path.exists():
            raise ModelRegistryError(f"Missing training manifest: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        self._manifest_cache[key] = data
        return dict(data)

    def assert_constitution_cleared(self, manifest: dict[str, Any]) -> None:
        if not manifest.get("constitution_cleared", False):
            raise ModelRegistryError("Model manifest is not constitution_cleared; refusing to load weights.")

    def register(
        self,
        model_type: str,
        release_id: str,
        *,
        weights_bytes: bytes | None = None,
        manifest: dict[str, Any],
        torch_module: Any | None = None,
    ) -> Path:
        """Persist weights + manifest after optional constitution enforcement."""
        enforce_model_registration(manifest)
        dest_dir = (self.root / release_id / model_type).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        man_path = dest_dir / "training_manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        wpath = dest_dir / "model.pt"
        if weights_bytes is not None:
            wpath.write_bytes(weights_bytes)
        elif torch_module is not None:
            try:
                import torch  # type: ignore

                torch.save(torch_module.state_dict(), wpath)
            except Exception as exc:
                raise ModelRegistryError(f"Failed to torch.save model: {exc}") from exc
        latest = self.root / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(release_id, target_is_directory=True)
        except OSError:
            logger.warning("Unable to update ML model latest symlink: %s", latest, exc_info=True)
        return dest_dir


def enforce_model_registration(manifest: dict[str, Any], *, raise_on_red: bool = True) -> list[str]:
    """Minimal constitution gate for training provenance (expand at integration time)."""
    violations: list[str] = []
    paths = manifest.get("training_data_paths") or manifest.get("training_data_path")
    if isinstance(paths, str):
        paths = [paths]
    if isinstance(paths, list):
        for p in paths:
            low = str(p).lower()
            if "ml_signals" in low or "deformation_runs" in low:
                violations.append(f"disallowed_training_path:{p}")
    if violations:
        if raise_on_red:
            raise ModelRegistryError("Constitution enforcement failed: " + "; ".join(violations))
        return violations
    manifest.setdefault("constitution_cleared", True)
    return violations
