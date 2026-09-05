from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.research_corpus import (
    DEFAULT_NUMERIC_EVIDENCE_TYPE,
    DEFAULT_PROXY_CORE_PERMISSION,
    CorpusDocumentManifest,
    DocumentType,
    NumericEvidenceType,
    ProviderGroup,
    UsageTag,
    provider_group_for,
)
from src.research_corpus.manifest import CorpusDocumentSeed
from src.research_corpus.providers.brevan_howard import BrevanHowardProvider, classify_document


class ResearchCorpusTests(unittest.TestCase):
    def test_provider_groups_include_requested_institutions(self) -> None:
        self.assertEqual(provider_group_for("Brevan Howard"), ProviderGroup.MACRO_FUNDS)
        self.assertEqual(provider_group_for("AQR"), ProviderGroup.QUANT_SYSTEMATIC)
        self.assertEqual(provider_group_for("D. E. Shaw"), ProviderGroup.MULTI_STRATEGY_CREDIT)
        self.assertEqual(provider_group_for("OFR"), ProviderGroup.PUBLIC_INSTITUTIONS)

    def test_corpus_manifest_defaults_block_proxy_core(self) -> None:
        manifest = CorpusDocumentManifest(
            corpus_id="brevan_howard:test",
            provider="Brevan Howard",
            provider_group=ProviderGroup.MACRO_FUNDS,
            title="Test",
            publication_date=None,
            url="https://www.bhmacro.com/",
            local_path="data/raw/research_corpus/macro_funds/brevan_howard/test.html",
            file_hash="abc",
            document_type=DocumentType.WEBPAGE,
            usage_tags=(UsageTag.MACRO_REGIME_LANGUAGE,),
        )

        self.assertFalse(DEFAULT_PROXY_CORE_PERMISSION)
        self.assertEqual(DEFAULT_NUMERIC_EVIDENCE_TYPE, NumericEvidenceType.NARRATIVE_EVIDENCE)
        self.assertFalse(manifest.to_dict()["allowed_for_proxy_core"])
        self.assertEqual(manifest.to_dict()["numeric_evidence_type"], "narrative_evidence")

    def test_corpus_manifest_requires_manual_approval_for_proxy_core(self) -> None:
        with self.assertRaises(ValueError):
            CorpusDocumentManifest(
                corpus_id="bad",
                provider="Brevan Howard",
                title="Bad",
                publication_date=None,
                url="https://example.com",
                local_path="bad.pdf",
                file_hash="abc",
                document_type=DocumentType.FUND_REPORT,
                allowed_for_proxy_core=True,
            )

    def test_brevan_provider_archives_manifest_without_downloading(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = BrevanHowardProvider(
                corpus_root=root / "raw",
                manifest_root=root / "manifests",
            )
            seed = CorpusDocumentSeed(
                provider="Brevan Howard",
                title="BH Macro reports and accounts index",
                url="https://www.bhmacro.com/reporting/reports-and-accounts/",
                document_type=DocumentType.WEBPAGE,
            )

            manifest = provider.archive_seed(seed, download=False)

            self.assertTrue(Path(manifest.local_path).exists())
            self.assertIn("macro_funds/brevan_howard", manifest.local_path)
            self.assertFalse(manifest.allowed_for_proxy_core)
            self.assertEqual(manifest.numeric_evidence_type, NumericEvidenceType.NARRATIVE_EVIDENCE)
            self.assertTrue(list((root / "manifests").rglob("*.json")))

    def test_brevan_document_classifier(self) -> None:
        self.assertEqual(classify_document("Annual Report 2025.pdf"), DocumentType.ANNUAL_REPORT)
        self.assertEqual(classify_document("Interim report"), DocumentType.INTERIM_REPORT)
        self.assertEqual(classify_document("risk disclosure"), DocumentType.RISK_DISCLOSURE)
        self.assertEqual(classify_document("macro commentary"), DocumentType.MACRO_COMMENTARY)
        self.assertEqual(classify_document("news release"), DocumentType.NEWS_REFERENCE)


if __name__ == "__main__":
    unittest.main()
