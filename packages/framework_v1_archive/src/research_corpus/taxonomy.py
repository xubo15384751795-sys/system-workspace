from __future__ import annotations

from enum import Enum


class ProviderGroup(str, Enum):
    MACRO_FUNDS = "macro_funds"
    QUANT_SYSTEMATIC = "quant_systematic"
    MULTI_STRATEGY_CREDIT = "multi_strategy_credit"
    PUBLIC_INSTITUTIONS = "public_institutions"


class DocumentType(str, Enum):
    FUND_REPORT = "fund_report"
    ANNUAL_REPORT = "annual_report"
    INTERIM_REPORT = "interim_report"
    RISK_DISCLOSURE = "risk_disclosure"
    MACRO_COMMENTARY = "macro_commentary"
    NEWS_REFERENCE = "news_reference"
    PAPER = "paper"
    INTERVIEW = "interview"
    WEBPAGE = "webpage"
    OTHER = "other"


class UsageTag(str, Enum):
    METHODOLOGY_REFERENCE = "methodology_reference"
    MACRO_REGIME_LANGUAGE = "macro_regime_language"
    GLOBAL_MACRO_REFERENCE = "global_macro_reference"
    RATES_FX_LIQUIDITY_REFERENCE = "rates_fx_liquidity_reference"
    FUND_BEHAVIOR_SAMPLE = "fund_behavior_sample"
    INSTITUTIONAL_WRITING_REFERENCE = "institutional_writing_reference"
    INSTITUTION_CONTEXT = "institution_context"
    CASE_CONTEXT = "case_context"
    LANGUAGE_REFERENCE = "language_reference"
    LITERATURE_NOTE = "literature_note"


class NumericEvidenceType(str, Enum):
    NARRATIVE_EVIDENCE = "narrative_evidence"
    FORMAL_MARKET_DATA = "formal_market_data"


DEFAULT_PROXY_CORE_PERMISSION = False
DEFAULT_NUMERIC_EVIDENCE_TYPE = NumericEvidenceType.NARRATIVE_EVIDENCE


BREVAN_HOWARD_USAGE_TAGS = (
    UsageTag.MACRO_REGIME_LANGUAGE,
    UsageTag.GLOBAL_MACRO_REFERENCE,
    UsageTag.RATES_FX_LIQUIDITY_REFERENCE,
    UsageTag.FUND_BEHAVIOR_SAMPLE,
    UsageTag.INSTITUTIONAL_WRITING_REFERENCE,
)
