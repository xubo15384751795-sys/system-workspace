"""Brevan Howard research corpus provider — research only.

HTTP status: research_only_non_harvester
"""
from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from src.research_corpus.manifest import (
    CorpusDocumentManifest,
    CorpusDocumentSeed,
    sha256_file,
    slugify,
)
from src.research_corpus.registry import provider_group_for
from src.research_corpus.taxonomy import BREVAN_HOWARD_USAGE_TAGS, DocumentType


BREVAN_HOWARD_PROVIDER = "Brevan Howard"
DEFAULT_TOPICS = ("global_macro", "rates", "FX", "liquidity", "risk_management")
DEFAULT_ASSET_CLASS = ("rates", "FX", "liquid_markets")
DEFAULT_STRATEGY_FAMILY = ("global_macro",)


class BrevanHowardProvider:
    """Research-corpus provider for public Brevan Howard / BH Macro materials.

    This provider deliberately does not integrate with DataHub or proxy
    construction. It archives documents as narrative institutional evidence.
    """

    provider = BREVAN_HOWARD_PROVIDER
    corpus_group = "macro_funds"
    provider_slug = "brevan_howard"

    index_urls = (
        "https://www.bhmacro.com/",
        "https://www.bhmacro.com/investor-relations/",
        "https://www.bhmacro.com/reporting/reports-and-accounts/",
        "https://www.brevanhoward.com/",
    )

    def __init__(
        self,
        *,
        corpus_root: Path | str = Path("data/raw/research_corpus"),
        manifest_root: Path | str = Path("data/manifests/research_corpus"),
        timeout_sec: int = 30,
        user_agent: str = "StructuralRiskLab/0.1 research-corpus archiver",
    ) -> None:
        self.corpus_root = Path(corpus_root)
        self.manifest_root = Path(manifest_root)
        self.timeout_sec = timeout_sec
        self.user_agent = user_agent

    @property
    def local_root(self) -> Path:
        return self.corpus_root / self.corpus_group / self.provider_slug

    @property
    def local_manifest_root(self) -> Path:
        return self.manifest_root / self.corpus_group / self.provider_slug

    def seed_documents(self) -> list[CorpusDocumentSeed]:
        return [
            self._seed(
                title="BH Macro reports and accounts index",
                url="https://www.bhmacro.com/reporting/reports-and-accounts/",
                document_type=DocumentType.WEBPAGE,
            ),
            self._seed(
                title="BH Macro investor relations index",
                url="https://www.bhmacro.com/investor-relations/",
                document_type=DocumentType.WEBPAGE,
            ),
            self._seed(
                title="Brevan Howard official website",
                url="https://www.brevanhoward.com/",
                document_type=DocumentType.WEBPAGE,
            ),
        ]

    def discover(self, *, max_pages: int = 20) -> list[CorpusDocumentSeed]:
        """Discover public PDF/HTML references from conservative official indexes."""
        seeds = {seed.url: seed for seed in self.seed_documents()}
        for index_url in self.index_urls:
            try:
                body = self._fetch_bytes(index_url).decode("utf-8", errors="replace")
            except Exception:
                continue
            for link in _extract_links(body, index_url):
                if len(seeds) >= max_pages:
                    break
                if not _looks_relevant(link):
                    continue
                seeds.setdefault(link, self._seed(title=_title_from_url(link), url=link, document_type=classify_document(link)))
        return list(seeds.values())

    def archive_seed(self, seed: CorpusDocumentSeed, *, download: bool = True) -> CorpusDocumentManifest:
        local_path = self._local_path_for(seed)
        if download:
            content = self._fetch_bytes(seed.url)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
        elif not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(seed.url + "\n", encoding="utf-8")

        file_hash = sha256_file(local_path)
        corpus_id = f"brevan_howard:{slugify(seed.title)}:{file_hash[:12]}"
        manifest = CorpusDocumentManifest(
            corpus_id=corpus_id,
            provider=self.provider,
            provider_group=provider_group_for(self.provider),
            title=seed.title,
            publication_date=seed.publication_date,
            url=seed.url,
            local_path=local_path.as_posix(),
            file_hash=file_hash,
            document_type=seed.document_type,
            topics=seed.topics or DEFAULT_TOPICS,
            asset_class=seed.asset_class or DEFAULT_ASSET_CLASS,
            strategy_family=seed.strategy_family or DEFAULT_STRATEGY_FAMILY,
            usage_tags=seed.usage_tags or BREVAN_HOWARD_USAGE_TAGS,
            allowed_for_proxy_core=False,
            manual_approval=False,
            notes=(
                "Research corpus only. Numeric values in this document are "
                "narrative_evidence, not formal_market_data."
            ),
        )
        manifest.write_json(self.local_manifest_root / f"{slugify(seed.title)}_{file_hash[:12]}.json")
        return manifest

    def archive(self, seeds: Iterable[CorpusDocumentSeed] | None = None, *, download: bool = True) -> list[CorpusDocumentManifest]:
        active_seeds = list(seeds) if seeds is not None else self.seed_documents()
        return [self.archive_seed(seed, download=download) for seed in active_seeds]

    def _seed(self, *, title: str, url: str, document_type: DocumentType) -> CorpusDocumentSeed:
        return CorpusDocumentSeed(
            provider=self.provider,
            title=title,
            url=url,
            document_type=document_type,
            topics=DEFAULT_TOPICS,
            asset_class=DEFAULT_ASSET_CLASS,
            strategy_family=DEFAULT_STRATEGY_FAMILY,
            usage_tags=BREVAN_HOWARD_USAGE_TAGS,
        )

    def _local_path_for(self, seed: CorpusDocumentSeed) -> Path:
        parsed = urlparse(seed.url)
        suffix = Path(parsed.path).suffix.lower()
        if not suffix or len(suffix) > 8:
            suffix = ".html"
        return self.local_root / seed.document_type.value / f"{slugify(seed.title)}{suffix}"

    def _fetch_bytes(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_sec) as response:
            return response.read()


def classify_document(url_or_title: str) -> DocumentType:
    text = url_or_title.casefold()
    if "annual" in text:
        return DocumentType.ANNUAL_REPORT
    if "interim" in text or "half-year" in text or "half_year" in text:
        return DocumentType.INTERIM_REPORT
    if "risk" in text:
        return DocumentType.RISK_DISCLOSURE
    if "commentary" in text or "outlook" in text or "macro" in text:
        return DocumentType.MACRO_COMMENTARY
    if "news" in text or "press" in text:
        return DocumentType.NEWS_REFERENCE
    if "report" in text or text.endswith(".pdf"):
        return DocumentType.FUND_REPORT
    if text.startswith("http"):
        return DocumentType.WEBPAGE
    return DocumentType.OTHER


def normalize_seed(seed: CorpusDocumentSeed) -> CorpusDocumentSeed:
    if seed.provider != BREVAN_HOWARD_PROVIDER:
        raise ValueError("BrevanHowardProvider only accepts Brevan Howard seeds")
    return replace(
        seed,
        usage_tags=seed.usage_tags or BREVAN_HOWARD_USAGE_TAGS,
        topics=seed.topics or DEFAULT_TOPICS,
        asset_class=seed.asset_class or DEFAULT_ASSET_CLASS,
        strategy_family=seed.strategy_family or DEFAULT_STRATEGY_FAMILY,
    )


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def _extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    return [urljoin(base_url, link) for link in parser.links]


def _looks_relevant(url: str) -> bool:
    text = url.casefold()
    if not text.startswith(("https://", "http://")):
        return False
    domains = ("bhmacro.com", "brevanhoward.com")
    if not any(domain in urlparse(url).netloc.casefold() for domain in domains):
        return False
    terms = ("report", "accounts", "annual", "interim", "pdf", "investor", "macro", "commentary", "news")
    return any(term in text for term in terms)


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    stem = Path(parsed.path.rstrip("/") or parsed.netloc).stem or parsed.netloc
    return stem.replace("-", " ").replace("_", " ").strip().title()


__all__ = [
    "BREVAN_HOWARD_PROVIDER",
    "BrevanHowardProvider",
    "classify_document",
    "normalize_seed",
]
