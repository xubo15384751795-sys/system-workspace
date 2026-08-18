from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from workbench.paths import workspace_root as _workspace_root

logger = logging.getLogger(__name__)

ROOT = cast(Path, _workspace_root())
DATA_NLP = ROOT / "Data" / "nlp"
OUTPUT_NLP = ROOT / "Output" / "nlp"


class MarkdownConverter:
    """Convert documents to Markdown using MarkItDown with fallback adapters."""

    def __init__(self, timeout_sec: int = 60) -> None:
        self.timeout_sec = timeout_sec

    def convert(self, source_path: Path, *, force: bool = False) -> Path:
        suffix = source_path.suffix.lower()
        if suffix == ".md":
            return self._passthrough(source_path)
        if suffix == ".txt":
            return self._text_to_md(source_path)
        if suffix == ".pdf":
            return self._convert_pdf(source_path)
        if suffix in (".docx", ".doc"):
            return self._convert_docx(source_path)
        if suffix in (".pptx", ".ppt"):
            return self._convert_pptx(source_path)
        if suffix in (".html", ".htm"):
            return self._convert_html(source_path)
        raise ValueError(f"Unsupported source type: {suffix}")

    def _passthrough(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / source_path.name
        dest.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return dest

    def _text_to_md(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{source_path.stem}.md"
        text = source_path.read_text(encoding="utf-8", errors="replace")
        dest.write_text(text, encoding="utf-8")
        return dest

    def _convert_pdf(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{source_path.stem}.md"

        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(str(source_path))
            dest.write_text(result.text_content, encoding="utf-8")
            return dest
        except Exception:
            logger.debug("MarkItDown PDF conversion unavailable for %s", source_path, exc_info=True)

        try:
            import pdfplumber

            lines: list[str] = []
            with pdfplumber.open(str(source_path)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        lines.append(text)
            dest.write_text("\n\n".join(lines), encoding="utf-8")
            return dest
        except Exception:
            raise RuntimeError(
                f"Failed to convert PDF {source_path}. "
                "Install markitdown or pdfplumber."
            )

    def _convert_docx(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{source_path.stem}.md"

        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(str(source_path))
            dest.write_text(result.text_content, encoding="utf-8")
            return dest
        except Exception:
            logger.debug("MarkItDown DOCX conversion unavailable for %s", source_path, exc_info=True)

        try:
            import docx

            document = docx.Document(str(source_path))
            lines: list[str] = []
            for para in document.paragraphs:
                if para.style.name.startswith("Heading"):
                    level = int(para.style.name.split()[-1]) if para.style.name.split()[-1].isdigit() else 1
                    lines.append(f"{'#' * level} {para.text}")
                else:
                    lines.append(para.text)
            dest.write_text("\n\n".join(lines), encoding="utf-8")
            return dest
        except Exception:
            raise RuntimeError(
                f"Failed to convert DOCX {source_path}. Install markitdown or python-docx."
            )

    def _convert_pptx(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{source_path.stem}.md"

        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(str(source_path))
            dest.write_text(result.text_content, encoding="utf-8")
            return dest
        except Exception:
            raise RuntimeError(
                f"Failed to convert PPTX {source_path}. Install markitdown."
            )

    def _convert_html(self, source_path: Path) -> Path:
        out_dir = DATA_NLP / "parsed_markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{source_path.stem}.md"

        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(str(source_path))
            dest.write_text(result.text_content, encoding="utf-8")
            return dest
        except Exception:
            logger.debug("MarkItDown HTML conversion unavailable for %s", source_path, exc_info=True)

        try:
            from bs4 import BeautifulSoup

            html = source_path.read_text(encoding="utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text("\n")
            dest.write_text(text, encoding="utf-8")
            return dest
        except Exception:
            raise RuntimeError(
                f"Failed to convert HTML {source_path}. Install markitdown or beautifulsoup4."
            )
