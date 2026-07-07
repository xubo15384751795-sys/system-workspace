from __future__ import annotations

from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from nlp.ingestion.markdown_converter import MarkdownConverter
from nlp.ingestion.source_manifest import SourceManifest, write_source_manifest

ROOT = _workspace_root()


class DocumentLoader:
    """Unified document loader: ingest → convert → manifest."""

    def __init__(self, converter: MarkdownConverter | None = None) -> None:
        self.converter = converter or MarkdownConverter()

    def load(self, source_path: Path) -> tuple[Path, SourceManifest]:
        resolved = source_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Source document not found: {resolved}")

        suffix = resolved.suffix.lower()
        doc_id = f"doc_{resolved.stem}"

        issues: list[str] = []
        try:
            output_path = self.converter.convert(resolved)
            status = "success"
        except Exception as exc:
            output_path = resolved
            status = "failed"
            issues.append(str(exc))

        manifest = SourceManifest(
            document_id=doc_id,
            source_type=suffix.lstrip("."),
            source_path=str(resolved),
            converted_by="markitdown",
            output_path=str(output_path),
            conversion_status=status,
            known_issues=issues,
        )
        write_source_manifest(manifest)
        return output_path, manifest


def load_document(path: str | Path) -> tuple[Path, SourceManifest]:
    loader = DocumentLoader()
    return loader.load(Path(path))
