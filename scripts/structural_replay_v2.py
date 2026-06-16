#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ACTIVE LOCATION — canonical workspace entrypoint for structural replay.
# This script contains the full replay logic (not a thin wrapper).
# Registered in governance/daily_pipeline_registry.yaml as step 5.
# ─────────────────────────────────────────────────────────────────────────────
"""Structural Deformation System — Historical Case Replay v2.

Uses the official Harvester panel (2026-05-05-r1) with 27 series across
FRED, H41, SEC, Treasury, and yfinance sources.  Builds M/D/K/X proxies
from real structural preset components rather than yfinance approximations.

Output:
  Output/sandbox/structural_replay_v2/
    evaluation_report.md
    event_windows/
    results.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd
from omegaconf import DictConfig, OmegaConf

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_SRC = REPO_ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.report_gate import validate_report_verdict
from workbench.governance.semantic import SemanticRegistry, build_sigma_vector

CONFIG_PATH = (
    REPO_ROOT / "configs" / "structural_replay" / "config.yaml"
)
SEMANTIC_REGISTRY_PATH = REPO_ROOT / "governance" / "semantic_registry.json"


def load_cfg() -> DictConfig:
    """Load YAML config and merge Hydra-style ``key=value`` overrides from argv.

    Examples:
        python scripts/structural_replay_v2.py
        python scripts/structural_replay_v2.py panel.release_id=2026-04-22-r1
        python scripts/structural_replay_v2.py run.tag=weekly output.subdir=runs/weekly
    """
    base = OmegaConf.load(CONFIG_PATH)
    overrides = OmegaConf.from_cli(sys.argv[1:])
    return OmegaConf.merge(base, overrides)

# ── Frequency / Tier / Activation typing ────────────────────────────────────

Freq = Literal["daily", "weekly", "monthly", "quarterly", "sparse", "mixed"]
Tier = Literal["core", "auxiliary", "diagnostic_only", "experimental", "deprecated"]
ActivationLogic = Literal["continuous", "event_jump", "official_facility", "mixed"]

# ── Stress Events ────────────────────────────────────────────────────────────

STRESS_EVENTS = [
    {
        # Phase 5 cleanup: added so X_REALIZED activations during the Asian
        # crisis are not counted as "calm-window false alarms".
        "id": "asian_1997", "name": "Asian Financial Crisis",
        "peak": "1997-10-27", "start": "1997-07-02", "end": "1998-01-31",
        "pre_start": "1997-04-01", "post_end": "1998-04-30",
        "category": "em_currency_credit",
    },
    {
        "id": "ltcm_1998", "name": "LTCM / Russia Default",
        "peak": "1998-09-23", "start": "1998-07-01", "end": "1998-12-31",
        "pre_start": "1997-06-01", "post_end": "1999-06-01",
        "category": "credit_liquidity",
    },
    {
        "id": "dotcom_2000", "name": "Dot-com Bubble Burst",
        "peak": "2000-03-10", "start": "2000-01-01", "end": "2000-06-30",
        "pre_start": "1999-01-01", "post_end": "2000-12-31",
        "category": "equity_valuation",
    },
    {
        # Phase 5 cleanup: post-9/11 + WorldCom corporate accounting collapse
        # period; X_REALIZED activates here via VIX_JUMP, properly classified.
        "id": "worldcom_2002", "name": "WorldCom / Corporate Accounting Collapse",
        "peak": "2002-07-22", "start": "2002-06-01", "end": "2002-10-31",
        "pre_start": "2002-03-01", "post_end": "2003-01-31",
        "category": "corporate_accounting_credit",
    },
    {
        "id": "gfc_2008", "name": "GFC / Lehman",
        "peak": "2008-09-15", "start": "2008-07-01", "end": "2009-03-31",
        "pre_start": "2007-07-01", "post_end": "2009-06-30",
        "category": "credit_liquidity_systemic",
    },
    {
        "id": "flash_crash_2010", "name": "Flash Crash",
        "peak": "2010-05-06", "start": "2010-05-01", "end": "2010-06-30",
        "pre_start": "2010-01-01", "post_end": "2010-08-31",
        "category": "liquidity_technical",
    },
    {
        "id": "euro_debt_2011", "name": "US Downgrade / EU Debt Crisis",
        "peak": "2011-08-08", "start": "2011-07-01", "end": "2011-12-31",
        "pre_start": "2011-01-01", "post_end": "2012-03-31",
        "category": "sovereign_credit",
    },
    {
        "id": "taper_2013", "name": "Taper Tantrum",
        "peak": "2013-06-19", "start": "2013-05-01", "end": "2013-09-30",
        "pre_start": "2013-01-01", "post_end": "2013-12-31",
        "category": "rates_volatility",
    },
    {
        "id": "china_2015", "name": "China Devaluation / HY Stress",
        "peak": "2015-08-24", "start": "2015-08-01", "end": "2016-02-29",
        "pre_start": "2015-01-01", "post_end": "2016-06-30",
        "category": "credit_em",
    },
    {
        # Phase 5 cleanup: Brexit referendum vote shock; X_REALIZED activates
        # via VIX_JUMP for ~10 days — properly inside an event window now.
        "id": "brexit_2016", "name": "Brexit Referendum",
        "peak": "2016-06-24", "start": "2016-06-20", "end": "2016-07-29",
        "pre_start": "2016-04-01", "post_end": "2016-09-30",
        "category": "political_volatility",
    },
    {
        "id": "volmageddon_2018", "name": "Volmageddon",
        "peak": "2018-02-05", "start": "2018-01-15", "end": "2018-03-31",
        "pre_start": "2017-09-01", "post_end": "2018-06-30",
        "category": "volatility_technical",
    },
    {
        "id": "repo_2019", "name": "Repo Market Stress",
        "peak": "2019-09-17", "start": "2019-09-01", "end": "2019-12-31",
        "pre_start": "2019-06-01", "post_end": "2020-02-29",
        "category": "funding_liquidity",
    },
    {
        "id": "covid_2020", "name": "COVID-19 Crisis",
        "peak": "2020-03-23", "start": "2020-02-15", "end": "2020-06-30",
        "pre_start": "2019-09-01", "post_end": "2020-09-30",
        "category": "systemic_all_channel",
    },
    {
        "id": "ldi_2022", "name": "UK LDI / Gilt Crisis",
        "peak": "2022-09-28", "start": "2022-09-01", "end": "2022-12-31",
        "pre_start": "2022-06-01", "post_end": "2023-03-31",
        "category": "rates_leverage",
    },
    {
        "id": "svb_2023", "name": "SVB / Regional Banking Crisis",
        "peak": "2023-03-10", "start": "2023-03-01", "end": "2023-06-30",
        "pre_start": "2023-01-01", "post_end": "2023-09-30",
        "category": "banking_funding",
    },
    {
        "id": "august_2024", "name": "August 2024 Carry Unwind",
        "peak": "2024-08-05", "start": "2024-07-01", "end": "2024-09-30",
        "pre_start": "2024-04-01", "post_end": "2024-12-31",
        "category": "carry_unwind",
    },
]


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_official_panel(panel_path: Path) -> pd.DataFrame:
    """Load the official Harvester panel and return wide-format DataFrame.

    Built manually as per-series Series → DataFrame to avoid a pandas/
    numpy datetime64[us] bug (seen on Python 3.14) where pivot_table /
    unstack on this parquet produces an index whose int64 timestamp
    values are silently corrupted into 1953-1957 range — causing all
    .loc[real_date] lookups to fail or return wrong rows. See
    investigation 2026-05-18 in conversation history.
    """
    raw = pd.read_parquet(panel_path)
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.drop_duplicates(subset=["date", "series_id"], keep="first")
    wide_dict: dict[str, pd.Series] = {}
    for sid, sub in raw.groupby("series_id"):
        wide_dict[sid] = pd.Series(
            sub["value"].values,
            index=pd.DatetimeIndex(sub["date"].values),
        )
    wide = pd.DataFrame(wide_dict).sort_index()
    return wide


# ── Variable Layer (theoretical state variables / 状态量本体) ───────────────
#
# 这是体系的「测量宪法」。每个变量定义自己的物理含义、应有频率、激活逻辑、
# 必须独立于哪些其他变量，以及验证问题。
#
# 代理 (ProxySpec) 通过 target_variable 字段绑定到这一层；代理可以增删替换，
# 但变量定义保持稳定。代理不能反过来定义变量。
#
# audit 层依据该宪法检查：
#   1) proxy.freq 是否兼容 variable.expected_freq
#   2) 必须独立的变量对，其代理不应出现 derivative / family contamination

# Canonical channels (Finance-2.tex §4.1 + §7.2): the four primitive latent
# variables M_t, D_t, K_t, X_t^agg, plus the derived realization-pressure
# observable layer Π_t. The legacy channels X_PRE and X_REALIZED are kept in
# CHANNELS for backward compatibility (audit, downstream code) but every proxy
# pointed at them is marked canonical_status='extension_beyond_canonical', so
# they evaluate to NaN under the canonical voting rule.
CHANNELS = ["M", "D_contraction", "K", "X_agg", "X_PRE", "X_REALIZED", "Pi_t"]


# Known data gaps that limit the proxy registry. These are not measurement-
# layer problems (the math here is fine); they are Harvester / data-acquisition-
# layer items. Recorded so audit output can flag them, and so future Harvester
# upgrades have a clear shopping list. Each entry says: which channel is
# affected, why we cannot resolve it inside this script, what would unblock it.
KNOWN_DATA_GAPS: list[dict] = [
    {
        "channel": "M",
        "issue": "100% FRED_RATES family",
        "blocker": "all daily rate / curve / policy series belong to the FRED rates family by construction",
        "unblock": "no action required — family monoculture is structurally appropriate for M (anchor-mismatch is, by definition, an interest-rate-curve mechanism)",
        "owner": "measurement_layer",
    },
    {
        "channel": "D_contraction",
        "issue": "100% FRED_FUNDING family (CP-bill + SOFR-IORB + SOFR-DFF all FRED short-end instruments)",
        "blocker": "TGA daily balance harvester data stops 2022-09-08; no ON RRP, reserve balances, OFR FSI, or non-FRED funding-stress sources in the panel",
        "unblock": "Harvester-side: re-enable daily_treasury_statement post-2022, add ON RRP volume (RRPONTSYD), reserve balances (WRBWFRBL), OFR Financial Stress Index",
        "owner": "harvester",
    },
    {
        "channel": "X_PRE",
        "issue": "still leans on NFCI family at 50%",
        "blocker": "no VIX term-structure series (VIX9D vs VIX), no Kansas City FSI, no HY ETF-NAV discount in panel",
        "unblock": "Harvester-side: add VIX9D, KCFSI, HY ETF NAV-vs-price spread; would let X_PRE drop NFCI weight below 33%",
        "owner": "harvester",
    },
    {
        "channel": "X_REALIZED",
        "issue": "MARKET-side OAS_JUMP only available 2023-05+",
        "blocker": "FRED ICE OAS series (BAMLH0A0HYM2, BAMLC0A0CM, BAMLC0A4CBBB) are gated on the 3-year public CSV window; full history requires API key (see project_fred_ice_license memory)",
        "unblock": "FRED API key in Harvester credentials; would extend OAS_JUMP coverage back to ~1996",
        "owner": "harvester",
    },
]


@dataclass(frozen=True)
class StateVariable:
    """Theoretical state variable. Its proxies are derived; it itself is fixed."""

    name: str
    description: str
    physical_meaning: str
    expected_freq: Freq
    activation_logic: ActivationLogic
    must_be_independent_of: tuple[str, ...]
    historical_validity_window: tuple[str | None, str | None]
    validation_questions: tuple[str, ...]
    # Frequencies a variable accepts as legitimate fallbacks alongside its
    # primary expected_freq. Intended for variables whose primary horizon
    # is high-frequency but which retain low-frequency proxies for long
    # historical coverage (e.g. K = daily OAS surface + monthly BAA10YM
    # historical anchor). horizon_consistency does not flag these mixes.
    historical_fallback_freqs: tuple[Freq, ...] = ()
    # v2 core contract: which independence_groups are allowed / forbidden in CORE proxies
    core_contract: dict = field(default_factory=dict)
    # Canonical alignment (Finance-2.tex red line, see governance/canonical_proxy_spec.yaml).
    # canonical_status taxonomy:
    #   "canonical_primary"          — matches a canonical latent variable in Finance-2.tex.
    #   "drifted_pending_repair"     — historical StateVariable whose core_contract diverges
    #                                  from the canonical spec; preserved for audit; voting
    #                                  superseded by a canonical_primary alias (e.g. X_agg
    #                                  supersedes the split X_PRE/X_REALIZED).
    #   "extension_beyond_canonical" — engineering-layer extension not in canonical paper.
    #                                  Kept for backward compatibility; does not vote.
    #   "derived_observation_layer"  — derived quantity (e.g. Π_t) whose proxies are used
    #                                  only for downstream validation, never for voting.
    canonical_status: str = "unevaluated"
    canonical_section_ref: str = ""
    canonical_alignment_note: str = ""


VARIABLES: dict[str, StateVariable] = {
    "M": StateVariable(
        name="M",
        description="Anchor Mismatch / 锚定错配 (canonical M_t = Δ_M(S_t, A_t))",
        physical_meaning="结构状态 S_t 与锚定配置 A_t 之间的非对称差异：funding-anchor gap、verifiability gap、liquidation gap 三个子篮",
        expected_freq="daily",
        activation_logic="continuous",
        must_be_independent_of=("D_contraction", "K", "X_agg"),
        historical_validity_window=(None, None),
        validation_questions=(
            "M 的代理是否覆盖 funding/verifiability/liquidation 三个 canonical 子篮？",
            "M 是否承担其他通道无法承担的独立信息？",
        ),
        core_contract={
            # Aligned with canonical spec: M groups should reflect anchor-gap
            # mechanisms (funding-anchor / verifiability / liquidation), not
            # pure rates-curve slope.
            "allowed_groups": (
                "funding_anchor_gap", "verifiability_gap", "liquidation_gap",
                # Legacy groups kept so quarantined proxies still parse; they
                # are no longer canonical-aligned.
                "policy_rate_spread",
            ),
            "forbidden_groups": (
                "credit_surface", "funding_spread", "volatility_jump",
                "official_liquidity_facility", "broad_financial_conditions_composite",
                "rates_curve",  # added: T10Y2Y slope is not anchor-mismatch per canonical
            ),
        },
        canonical_status="canonical_primary",
        canonical_section_ref="Finance-2.tex §4.2 + §7.2.4 + Table 6",
        canonical_alignment_note=(
            "Canonical M is the asymmetric discrepancy Δ_M(S_t, A_t). "
            "Proxy basket = (m1 funding-anchor gap, m2 verifiability gap, "
            "m3 liquidation gap), aggregated by a Huber-type / weighted-L1 "
            "operator. Simple mean is not canonical."
        ),
    ),
    "D_contraction": StateVariable(
        name="D_contraction",
        description="Effective Degrees of Freedom / 可行行动空间 (canonical D_t = [d_0 + d_L L + d_V V - d_P P - d_τ τ - d_M M]_+)",
        physical_meaning="path feasibility 三联：market depth、hedge breadth、funding access (canonical w1+w2+w3)",
        expected_freq="daily",
        activation_logic="continuous",
        must_be_independent_of=("M", "K", "X_agg"),
        historical_validity_window=(None, None),
        validation_questions=(
            "D 的代理是否覆盖 depth / hedge breadth / funding access 三个 canonical 子篮？",
            "D 是否仅在融资紧张事件中激活，而不是在所有压力事件中跟随 PC1？",
        ),
        core_contract={
            "allowed_groups": (
                "market_depth", "hedge_breadth", "funding_access",
                # Legacy groups for quarantined proxies; not canonical primary.
                "funding_spread", "reserve_liquidity", "treasury_cash",
            ),
            "forbidden_groups": (
                "credit_surface", "broad_financial_conditions_composite",
                "volatility_jump", "official_liquidity_facility",
            ),
        },
        canonical_status="canonical_primary",
        canonical_section_ref="Finance-2.tex §4.2 + §7.2.1 + Table 6",
        canonical_alignment_note=(
            "Canonical D combines market depth (bid-ask, book depth), hedge "
            "breadth (option OI, cross-maturity), and funding access "
            "(repo/margin/haircut). Current implementation has only the "
            "funding-access bucket; depth and hedge breadth are awaiting_data."
        ),
    ),
    "K": StateVariable(
        name="K",
        description="Effective Transition Curvature / 转换映射形变 (canonical K_t = K(g_t) ≍ sup ‖D_z J_t(z)‖_op)",
        physical_meaning=(
            "local transition map 的形变率：IV 曲面 distortion / realized jump intensity / "
            "tail convexity。**红线明令排除**：不是 vol amplitude、不是 jump amplitude、"
            "不是 tail mass、不是 VIX、**不是信用利差**（信用利差是 X_agg 或 D 的领地）"
        ),
        expected_freq="daily",
        activation_logic="continuous",
        must_be_independent_of=("M", "D_contraction", "X_agg"),
        historical_validity_window=(None, None),
        validation_questions=(
            "K 的代理是否来自期权 IV / realized jump / OTM put richness 这三类？",
            "K 是否独立于 vol / jump / tail benchmark（§7.2.2 falsification gate）？",
            "K 是否真正捕捉 transition map 形变，而不是任何价格利差水平？",
        ),
        historical_fallback_freqs=("monthly",),
        core_contract={
            # Canonical-aligned allowed groups: options-derived nonlinearity
            # mechanisms. The previous "credit_surface" allow was a red-line
            # violation (§4.4 explicitly excludes credit interpretation of K).
            "allowed_groups": (
                "iv_distortion", "jump_intensity", "tail_convexity",
                # Legacy groups for quarantined proxies; NOT canonical.
                "credit_surface", "convexity_surface", "cross_asset_curvature",
            ),
            "forbidden_groups": (
                "funding_spread", "official_liquidity_facility",
                "volatility_jump",   # vol amplitude ≠ K curvature
                "rates_curve",
                # Note: credit_surface should also be forbidden under strict
                # canonical reading, but is kept in allowed_groups for
                # transition compatibility while old proxies sit in quarantine.
            ),
        },
        canonical_status="drifted_pending_repair",
        canonical_section_ref="Finance-2.tex §4.4 + §7.2.2 + Table 6",
        canonical_alignment_note=(
            "Canonical K requires IV-surface distortion + jump intensity + "
            "tail convexity. UPDATE 2026-05-31: the IV-surface data IS in "
            "harvester (CBOE SKEW, VIX9D/VIX3M/VIX6M term structure). u1 "
            "(term-structure twist butterfly) and u3 (SKEW tail convexity) are "
            "now wired as candidate_pending_promotion (NON-voting); u2 (jump "
            "intensity) still awaiting_data (needs intraday/bipower). The 5 "
            "legacy credit-spread K proxies remain quarantined red-line "
            "violations (§4.4: NOT vol/jump/tail/VIX/credit-spread). K still "
            "aggregates to NaN today (no canonical_voting K proxy yet); the "
            "candidates promote only after the §7.2.2 falsification gate + "
            "independence checks pass — this is the honest state."
        ),
    ),
    "X_PRE": StateVariable(
        name="X_PRE",
        description="[LEGACY / extension_beyond_canonical] Shadow Accumulation (爆发前) — superseded by X_agg",
        physical_meaning="原工程层引入的 X 拆分，不在 Finance-2.tex 中。canonical 只有单一 X_t^agg。",
        expected_freq="weekly",
        activation_logic="continuous",
        must_be_independent_of=("M", "D_contraction", "K"),
        historical_validity_window=(None, None),
        validation_questions=(
            "(legacy) 这个 channel 不再 vote，所有问题已迁移到 X_agg。",
        ),
        core_contract={
            "allowed_groups": ("hidden_leverage", "broad_stress_non_core",
                               "pre_realization_pressure"),
            "forbidden_groups": ("volatility_jump", "official_liquidity_facility",
                                 "rates_curve", "funding_spread"),
        },
        canonical_status="extension_beyond_canonical",
        canonical_section_ref="(no canonical counterpart; engineering extension)",
        canonical_alignment_note=(
            "X_PRE was an engineering split introduced 2026-05-09 (commit "
            "6b934ad). It is not in Finance-2.tex which has only a single "
            "X_t^agg (stock) + derived Π_t (realization pressure). All "
            "X_PRE proxies are now quarantined; canonical voting goes "
            "through X_agg."
        ),
    ),
    "X_REALIZED": StateVariable(
        name="X_REALIZED",
        description="[LEGACY / extension_beyond_canonical] Forced Realization — superseded by Π_t derived layer",
        physical_meaning="原工程层引入的 X 拆分，不在 Finance-2.tex 中。realization 是从 D/K/X_agg 派生的 Π_t。",
        expected_freq="mixed",
        activation_logic="mixed",
        must_be_independent_of=("M", "D_contraction", "K"),
        historical_validity_window=(None, None),
        validation_questions=(
            "(legacy) 这个 channel 不再 vote。H41 facility usage 数据迁移到 Π_t observation 层。",
        ),
        core_contract={
            "allowed_groups": ("official_liquidity_facility", "volatility_jump",
                               "forced_liquidation_marker"),
            "forbidden_groups": ("credit_surface", "funding_spread",
                                 "rates_curve", "hidden_leverage"),
        },
        canonical_status="extension_beyond_canonical",
        canonical_section_ref="(no canonical counterpart; engineering extension)",
        canonical_alignment_note=(
            "X_REALIZED was an engineering split introduced 2026-05-09. "
            "Canonical has Π_t = ρ_0 + ρ_D(D_crit-D)+ + ρ_K(K-K*)+ + ρ_ξ "
            "as a DERIVED quantity (§4.5), not a voting channel. H41 "
            "facility usage (primary credit / discount window / BTFP) is "
            "an OBSERVABLE of Π firing, not an input to X. Those proxies "
            "are reassigned_to_pi_observable."
        ),
    ),
    # ── Canonical primary X (Finance-2.tex §4.5 + §7.2.3) ─────────────────
    "X_agg": StateVariable(
        name="X_agg",
        description="Aggregate Shadow Mass / 隐性结构堆积 (canonical X_t^agg = ∫_Ξ X_t(ξ) dξ = μ_t(Ξ))",
        physical_meaning=(
            "尚未在当前 σ-algebra 中显化的经济相关 mass。三个子篮："
            "OBS / contingent liabilities (v1)、hidden leverage / TRS / synthetic exposure (v2)、"
            "shadow funding substitution / collateral transformation (v3)。"
        ),
        expected_freq="weekly",
        activation_logic="continuous",
        must_be_independent_of=("M", "D_contraction", "K"),
        historical_validity_window=(None, None),
        validation_questions=(
            "X_agg 是否覆盖 OBS / hidden leverage / shadow funding 三个子篮？",
            "X_agg 是否独立于 broad stress benchmarks（不是 NFCI/STLFSI 的重新包装）？",
        ),
        core_contract={
            "allowed_groups": (
                "off_balance_sheet", "hidden_leverage_canonical", "shadow_funding_substitution",
            ),
            "forbidden_groups": (
                "volatility_jump", "official_liquidity_facility",
                "rates_curve", "funding_spread", "credit_surface",
                "broad_financial_conditions_composite",
            ),
        },
        canonical_status="canonical_primary",
        canonical_section_ref="Finance-2.tex §4.5 + §7.2.3 + Table 6",
        canonical_alignment_note=(
            "Single canonical X channel. The current implementation only has "
            "a weak NFCILEVERAGE proxy for v2; v1 (OBS) and v3 (shadow funding) "
            "have no data and are awaiting_data."
        ),
    ),
    # ── Derived observation layer (Finance-2.tex §4.5 + §4.7) ─────────────
    "Pi_t": StateVariable(
        name="Pi_t",
        description="Forced Realization Pressure / 强制兑现压力 (canonical Π_t = ∫ R_t(ξ) X_t(ξ) dξ, DERIVED)",
        physical_meaning=(
            "派生量：从 D / K / X_agg + 强度系数 ρ_0, ρ_D, ρ_K, ρ_ξ 计算。"
            "不是 voting channel。H41 facility usage 等数据是 Π firing 的 observables，"
            "用于下游一致性验证，不进 X_agg。"
        ),
        expected_freq="sparse",
        activation_logic="event",
        must_be_independent_of=(),  # derived; independence concept N/A
        historical_validity_window=(None, None),
        validation_questions=(
            "Π_t observable 是否仅作为下游验证使用，没有反流回 X_agg？",
        ),
        core_contract={
            "allowed_groups": ("official_liquidity_facility", "forced_liquidation_marker"),
            "forbidden_groups": (),
        },
        canonical_status="derived_observation_layer",
        canonical_section_ref="Finance-2.tex §4.5 + §4.7",
        canonical_alignment_note=(
            "Π_t is a derived quantity, not a primitive channel. Its proxies "
            "are validation observables for D/K/X-implied realization events. "
            "Singular regime requires D ≤ ε_D ∧ K ≥ K* ∧ Π ≥ Π* (§4.7)."
        ),
    ),
}


# ── Proxy Layer (observable implementations / 代理实现层) ───────────────────


@dataclass(frozen=True)
class ProxySpec:
    """One observable proxy component bound to a target StateVariable.

    Proxies can be added, replaced, or deprecated. The variable they target
    is fixed in VARIABLES and cannot be redefined by adding/removing proxies.
    """

    name: str
    target_variable: str
    tier: Tier
    freq: Freq
    raw_series: tuple[str, ...]
    raw_family: str
    mechanism: str
    transform: str
    builder: Callable[[pd.DataFrame], pd.Series | None]
    allow_derivative_reuse: bool = False
    independence_group: str = ""  # v2: same group must not appear in CORE of multiple channels
    note: str = ""
    # Canonical alignment (Finance-2.tex red line, see governance/canonical_proxy_spec.yaml).
    # canonical_status taxonomy:
    #   "canonical_voting"                — passes red-line check; feeds channel aggregation.
    #   "awaiting_data"                   — slot reserved for a canonical sub-basket but the
    #                                       required data source is not yet in harvester.
    #                                       Builder returns None. Contributes nothing.
    #   "quarantined_drift"               — previously voting under a non-canonical
    #                                       interpretation. Disconnected from aggregation.
    #                                       Preserved for audit trail and possible re-mapping.
    #   "reassigned_to_pi_observable"     — mechanism is actually a Π_t observable (e.g. H41
    #                                       facility usage). Moved to derived observation layer;
    #                                       does not vote on any latent channel.
    #   "diagnostic_consistent"           — proxy was already tier=diagnostic_only and is
    #                                       consistent with canonical (e.g. funding acceleration
    #                                       as a second-derivative diagnostic of D).
    #   "extension_beyond_canonical"      — target_variable itself is not in canonical paper
    #                                       (e.g. X_PRE/X_REALIZED voting); proxy is dormant.
    #   "candidate_pending_promotion"     — has real data + a real builder, but is an interim
    #                                       source not yet promoted to canonical (e.g. Phase 1
    #                                       SEC-XBRL OBS pending FFIEC Y-9C + independence/§7.2.3
    #                                       checks). Visible in audit; contributes 0 to voting.
    #   "unevaluated"                     — not yet reviewed against canonical spec.
    canonical_status: str = "unevaluated"
    canonical_subbasket: str = ""  # e.g. "M.m1_funding_anchor_gap"
    canonical_alignment_note: str = ""

    # Backward-compat: old code reads `.role` / `.channel`. Provide them.
    @property
    def role(self) -> str:
        return self.tier

    @property
    def channel(self) -> str:
        return self.target_variable

    def __post_init__(self) -> None:
        if self.target_variable not in VARIABLES:
            raise ValueError(
                f"ProxySpec {self.name!r}: target_variable {self.target_variable!r} "
                f"not in VARIABLES (known: {sorted(VARIABLES)})"
            )


@dataclass
class MeasurementBundle:
    channels: pd.DataFrame
    components: pd.DataFrame
    coverage: pd.DataFrame
    confidence: pd.DataFrame
    registry: list[dict]
    audit: dict


def _series(panel: pd.DataFrame, col: str, limit: int = 5) -> pd.Series | None:
    if col not in panel.columns:
        return None
    return panel[col].astype(float).interpolate(limit=limit)


def _spread(panel: pd.DataFrame, left: str, right: str, limit: int = 5) -> pd.Series | None:
    lhs = _series(panel, left, limit)
    rhs = _series(panel, right, limit)
    if lhs is None or rhs is None:
        return None
    return lhs - rhs


def _butterfly(panel: pd.DataFrame, short: str, mid: str, long: str, limit: int = 5) -> pd.Series | None:
    """Curvature (butterfly) of a three-tenor term structure: short - 2*mid + long.

    Level-independent measure of term-structure twist/distortion: ~0 for a
    smooth monotone curve, nonzero when the curve kinks (e.g. front-end vol
    inversion under stress). Used for canonical K u1 (IV term-structure twist).
    """
    s = _series(panel, short, limit)
    m = _series(panel, mid, limit)
    l = _series(panel, long, limit)
    if s is None or m is None or l is None:
        return None
    return s - 2.0 * m + l


FREQ_WINDOWS: dict[Freq, tuple[int, int]] = {
    "daily":   (252, 126),  # 1y rolling, 6m warmup
    "weekly":  (52, 26),    # 1y rolling in weekly observations
    "monthly": (12, 6),     # 1y rolling in monthly observations
    "quarterly": (20, 8),   # 5y rolling in quarterly observations (1y is too few obs)
}

FREQ_SMOOTH_DEFAULT: dict[Freq, int] = {
    "daily":   21,
    "weekly":  3,
    "monthly": 1,
    "quarterly": 1,
    "sparse":  5,
}

PANDAS_RESAMPLE_RULE: dict[Freq, str] = {
    "weekly":  "W-FRI",
    "monthly": "ME",
    "quarterly": "QE",
}


def _rolling_zscore(series: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    """Causal rolling z-score with no look-ahead and explicit missing values."""
    mu = series.rolling(window=window, min_periods=min_periods).mean()
    sigma = series.rolling(window=window, min_periods=min_periods).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-4, 4)


def _freq_aware_zscore(series: pd.Series, freq: Freq) -> pd.Series:
    """Rolling z-score with the window scaled to the data's natural frequency.

    For weekly / monthly series the input is daily-aligned but the underlying
    cadence is sparser, so we resample to native frequency, run a same-horizon
    z-score there, and forward-fill back to daily so it can join the unified
    daily channel index.
    """
    if freq == "daily":
        w, mp = FREQ_WINDOWS["daily"]
        return _rolling_zscore(series, w, mp)

    if freq in ("weekly", "monthly", "quarterly"):
        rule = PANDAS_RESAMPLE_RULE[freq]
        native = series.dropna().resample(rule).last()
        if native.empty:
            return pd.Series(np.nan, index=series.index)
        w, mp = FREQ_WINDOWS[freq]
        z_native = _rolling_zscore(native, w, mp)
        # Forward-fill to daily index, but limit fill so old observations
        # don't creep into long gaps.
        max_fill = {"weekly": 7, "monthly": 35, "quarterly": 100}[freq]
        return z_native.reindex(series.index, method="ffill", limit=max_fill)

    raise ValueError(f"_freq_aware_zscore: unsupported freq {freq!r}")


def _jump_activation_score(
    series: pd.Series | None,
    smooth: int = 5,
) -> pd.Series | None:
    """Daily jump-driven activation score for continuous market-side series.

    Used for VIX / HY OAS where forced realization shows up as discrete shock
    days rather than facility usage. Pipeline:
        |Δ series(1d)| → rolling `smooth`-day mean
                       → daily 252d rolling z-score
                       → take positive part (clip to [0, 4])
    Output mirrors the shape of `_sparse_activation_score`: ≈ 0 in calm
    regimes, ≥1 during shock days.

    Phase 5: smooth shortened from 21d to 5d. The longer 21-day decay let a
    single VIX shock keep the score elevated for ~3 weeks even when markets
    had already calmed, inflating false_activation_rate. 5d means a shock
    decays back to baseline within a week, matching the physical "forced
    realization" half-life.

    The "positive part" matters: a negative z-score (an unusually quiet
    rolling mean) is not a forced-realization signal, so it's clipped to 0
    so it can't cancel an active facility on the OFFICIAL side.
    """
    if series is None:
        return None
    if not series.notna().any():
        return pd.Series(np.nan, index=series.index)
    delta = series.diff().abs()
    smoothed = delta.rolling(smooth, min_periods=max(1, smooth // 3)).mean()
    z = _freq_aware_zscore(smoothed, freq="daily")
    return z.clip(lower=0, upper=4)


def _sparse_activation_score(
    series: pd.Series,
    smooth: int = 5,
    lookback: int = 252,
) -> pd.Series:
    """Baseline-deviation score for sparse / event-driven series (H4.1 facilities).

    Phase 5 rewrite. Replaces the prior "non-zero = activated" design which
    treated 2003-2007 routine primary-credit borrowing as forced realization
    (it isn't — banks borrow at the discount window in normal times too).

    Forced realization means: facility usage is **anomalously high vs its own
    recent baseline**, not merely non-zero. We use a 252d rolling-window
    median as the baseline and rolling-std as the unit of surprise:

        log_use            = log1p(facility_level)
        baseline           = rolling_252d_median(log_use)
        spread             = rolling_252d_max(log_use) − baseline
        intensity          = clip( (log_use − baseline) / spread,  0, 1 )
        deviation_z        = (log_use − baseline) / rolling_252d_std(log_use)
        activated          = max( (deviation_z > 1.0) over last `smooth` days )
        score              = activated * (1 + 2*intensity), clipped to [0, 4]

    Output:
      0          — dormant or routine usage
      ≈ 1 - 1.5  — onset of anomaly
      ≈ 2 - 3    — full crisis-level usage (e.g. GFC peak, COVID peak)

    Days before the series' first observation remain NaN so audit code can
    distinguish "facility did not exist" from "facility existed and unused".
    """
    if not series.notna().any():
        return pd.Series(np.nan, index=series.index)
    first_obs = series.first_valid_index()
    s = series.fillna(0).clip(lower=0)
    log_use = np.log1p(s)

    min_periods = max(21, lookback // 12)
    roll = log_use.rolling(window=lookback, min_periods=min_periods)
    baseline = roll.median()
    top = roll.max()
    spread = (top - baseline).replace(0, np.nan)
    intensity = ((log_use - baseline) / spread).clip(lower=0, upper=1).fillna(0)
    intensity = intensity.rolling(smooth, min_periods=1).mean()

    std = roll.std().replace(0, np.nan)
    deviation_z = ((log_use - baseline) / std).fillna(0)
    activated = (deviation_z > 1.0).rolling(smooth, min_periods=1).max().fillna(0).astype(float)

    score = (activated * (1.0 + 2.0 * intensity)).clip(0, 4)
    if first_obs is not None:
        score = score.where(score.index >= first_obs, np.nan)
    return score


def _component(
    series: pd.Series | None,
    freq: Freq = "daily",
    smooth: int | None = None,
) -> pd.Series | None:
    """Smooth + freq-aware z-score, or sparse activation score when freq=='sparse'."""
    if series is None:
        return None
    smooth_n = smooth if smooth is not None else FREQ_SMOOTH_DEFAULT[freq]
    if freq == "sparse":
        return _sparse_activation_score(series, smooth=smooth_n)
    smoothed = series.rolling(smooth_n, min_periods=max(1, smooth_n // 3)).mean()
    return _freq_aware_zscore(smoothed, freq)


def _pct_component(
    series: pd.Series | None,
    periods: int = 63,
    smooth: int | None = None,
    freq: Freq = "daily",
) -> pd.Series | None:
    if series is None:
        return None
    return _component(series.pct_change(periods).abs(), freq=freq, smooth=smooth)


def _diff_abs(series: pd.Series | None, periods: int = 21) -> pd.Series | None:
    if series is None:
        return None
    return series.diff(periods).abs()


def _native_freq_diff_abs(
    series: pd.Series | None, freq: Freq, periods: int = 1
) -> pd.Series | None:
    """Take period-over-period absolute change on the data's native cadence.

    Daily-aligned ffill values give noisy ~0 diffs; for weekly/monthly proxies
    we resample to native cadence first, diff there, then ffill back to daily
    so the rest of the pipeline can run unchanged.
    """
    if series is None:
        return None
    if freq == "daily":
        return series.diff(periods).abs()
    rule = PANDAS_RESAMPLE_RULE[freq]
    native = series.dropna().resample(rule).last()
    if native.empty:
        return pd.Series(np.nan, index=series.index)
    delta = native.diff(periods).abs()
    max_fill = {"weekly": 7, "monthly": 35}[freq]
    return delta.reindex(series.index, method="ffill", limit=max_fill)


def _accel_abs(series: pd.Series | None, periods: int = 5) -> pd.Series | None:
    if series is None:
        return None
    return series.diff(periods).diff(periods).abs()


def _log1p_series(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return np.log1p(series.clip(lower=0))


PROXY_REGISTRY: list[ProxySpec] = [
    # ── M (Anchor Mismatch) ─────────────────────────────────────────────────
    ProxySpec(
        name="M_curve_inversion",
        target_variable="M",
        tier="diagnostic_only",  # downgraded from core: rates_curve is a forbidden_group for M
        freq="daily",
        raw_series=("FRED:T10Y2Y",),
        raw_family="FRED_RATES",
        independence_group="rates_curve",
        mechanism="anchor_mismatch",
        transform="negative 10Y-2Y curve, daily 21d mean, daily rolling z-score (252/126)",
        builder=lambda p: _component(-_series(p, "FRED:T10Y2Y"), freq="daily"),
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "T10Y2Y is a yield-curve slope, NOT an anchor-mismatch indicator. "
            "Canonical M (Finance-2.tex §7.2.4) requires funding-anchor / "
            "verifiability / liquidation gaps. Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="M_policy_bill_gap",
        target_variable="M",
        # tier=auxiliary preserves canonical_voting (aux still votes) while
        # keeping DGS3MO out of CORE — D_cp_bill_funding_access is the CORE
        # owner of DGS3MO via its CP-bill spread. CORE isolation audit passes.
        tier="auxiliary",
        freq="daily",
        raw_series=("FRED:DFF", "FRED:DGS3MO"),
        raw_family="FRED_RATES",
        independence_group="funding_anchor_gap",
        mechanism="policy_market_anchor_gap",
        transform="DFF minus 3M Treasury, daily 21d mean, daily rolling z-score",
        builder=lambda p: _component(_spread(p, "FRED:DFF", "FRED:DGS3MO"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="M.m1_funding_anchor_gap",
        canonical_alignment_note=(
            "DFF - DGS3MO is the gap between the policy anchor (DFF) and the "
            "operative short-rate (3M Treasury). This is a legitimate "
            "funding-anchor gap (canonical m1). Currently the sole canonical "
            "M voter; m2 (verifiability) and m3 (liquidation) are awaiting_data."
        ),
    ),
    ProxySpec(
        name="M_policy_prime_gap",
        target_variable="M",
        tier="auxiliary",
        freq="daily",
        raw_series=("FRED:DPRIME", "FRED:DFF"),
        raw_family="FRED_RATES",
        independence_group="policy_rate_spread",
        mechanism="bank_policy_anchor_gap",
        transform="prime rate minus effective fed funds, daily 21d mean, daily rolling z-score",
        builder=lambda p: _component(_spread(p, "FRED:DPRIME", "FRED:DFF"), freq="daily"),
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "Prime - DFF is a bank pricing convention spread, not an "
            "anchor-mismatch indicator under canonical M. Quarantined 2026-05-18."
        ),
    ),

    # ── D_contraction (Funding Drainage) ─────────────────────────────────────
    #
    # Phase 3 拆 NFCI 家族污染:
    #   - D 移除 NFCI 投票权(NFCICREDIT 降到 diagnostic_only)
    #   - D 引入两个隔夜操作市场 daily core: SOFR-IORB / SOFR-DFF
    #     这两个跟 CP-bill 同 family (FRED_FUNDING) 但 sub-mechanism 不同:
    #       CP-bill = 私部门短端 vs 国债短端 (信用+流动性混合)
    #       SOFR-IORB = 隔夜回购溢价 vs 政策下界 (回购市场压力)
    #       SOFR-DFF = 隔夜回购溢价 vs 政策中性 (2018-2021 桥接)
    #   - v2 core_status = PARTIAL_CORE: funding_spread 族可用但 reserve_liquidity
    #     和 treasury_cash 仍未接入 (marked as known data gap)
    ProxySpec(
        name="D_cp_bill_funding_access",
        target_variable="D_contraction",
        tier="core",
        freq="daily",
        raw_series=("FRED:DCPF3M", "FRED:DGS3MO"),
        raw_family="FRED_FUNDING",
        independence_group="funding_access",  # canonical w3
        mechanism="short_funding_access",
        transform="commercial paper minus 3M Treasury, daily 21d mean, daily rolling z-score",
        builder=lambda p: _component(_spread(p, "FRED:DCPF3M", "FRED:DGS3MO"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="D.w3_funding_access",
        canonical_alignment_note="CP - bill spread is a short-funding access proxy (canonical w3).",
    ),
    ProxySpec(
        name="D_sofr_iorb_gap",
        target_variable="D_contraction",
        tier="core",
        freq="daily",
        raw_series=("FRED:SOFR", "FRED:IORB"),
        raw_family="FRED_FUNDING",
        independence_group="funding_spread",
        mechanism="overnight_funding_premium_over_policy_floor",
        transform="SOFR minus IORB, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(_spread(p, "FRED:SOFR", "FRED:IORB"), freq="daily"),
        note="Available 2021-07-29+ (IORB start). Captures repo market premium over policy floor; "
             "Repo 2019 stress 不可见 (太早), 但 SVB / 2024 Carry / 2025+ 都能捕获。",
        canonical_status="canonical_voting",
        canonical_subbasket="D.w3_funding_access",
        canonical_alignment_note="SOFR - IORB is repo-floor stress (canonical w3 funding access).",
    ),
    ProxySpec(
        name="D_sofr_dff_gap",
        target_variable="D_contraction",
        tier="auxiliary",
        freq="daily",
        raw_series=("FRED:SOFR", "FRED:DFF"),
        raw_family="FRED_FUNDING",
        independence_group="funding_spread",
        mechanism="overnight_funding_premium_over_policy_target",
        transform="SOFR minus DFF, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(_spread(p, "FRED:SOFR", "FRED:DFF"), freq="daily"),
        note="Available 2018-04-03+ (SOFR start). Bridges 2018-2021 window before IORB exists.",
        canonical_status="canonical_voting",
        canonical_subbasket="D.w3_funding_access",
        canonical_alignment_note="SOFR - DFF is a funding-access proxy bridging 2018-2021 (canonical w3).",
    ),
    ProxySpec(
        name="D_funding_acceleration_diagnostic",
        target_variable="D_contraction",
        tier="diagnostic_only",
        freq="daily",
        raw_series=("FRED:DCPF3M", "FRED:DGS3MO"),
        raw_family="FRED_FUNDING",
        independence_group="funding_spread",
        mechanism="funding_stress_acceleration",
        transform="second difference of CP-bill spread, absolute, daily 21d mean, daily rolling z-score",
        builder=lambda p: _component(_accel_abs(_spread(p, "FRED:DCPF3M", "FRED:DGS3MO"), periods=5), freq="daily"),
        note="v2: migrated from K_cp_bill_acceleration. This is D's own funding-stress second derivative, "
             "not K's curvature. diagnostic_only, does not vote.",
        canonical_status="diagnostic_consistent",
        canonical_alignment_note="2nd-derivative diagnostic of D funding-spread; consistent with canonical scope.",
    ),
    ProxySpec(
        name="D_nfci_credit_conditions",
        target_variable="D_contraction",
        tier="diagnostic_only",  # Phase 3: 从 auxiliary 降级,与 X_PRE 共用 NFCI 家族,不再投票决定 D
        freq="weekly",
        raw_series=("FRED:NFCICREDIT",),
        raw_family="NFCI",
        independence_group="broad_financial_conditions_composite",
        mechanism="broad_credit_path_contraction",
        transform="NFCI credit subindex, weekly 1y rolling z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "FRED:NFCICREDIT", limit=7), freq="weekly"),
        note="Phase 3: demoted to diagnostic_only. NFCI is X_PRE territory; D should not double-count "
             "the same broad credit-conditions index. Visible in audit, not voting.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "NFCICREDIT is a broad credit-conditions benchmark, not a "
            "feasibility / path-contraction proxy. Quarantined 2026-05-18."
        ),
    ),

    # ── K (Curvature / Surface Deformation) ─────────────────────────────────
    #
    # Phase 2 引入 OAS 信用曲面作为 K 的日频 core。OAS 数据始于 2023-05-05,
    # 对 2023+ 事件 K 是高精度 daily surface;对 pre-2023 事件,K 退回 monthly
    # BAA10YM 长历史代理(降级为 auxiliary)。这是用户方案的"K 不要只有一个版本":
    #   K_DAILY_SURFACE = HY-IG / BBB-IG / Δ²(HY-IG)         (daily core, 2023+)
    #   K_HISTORICAL    = BAA10YM level / delta (monthly aux, 1953+)
    # v2: OAS credit surface data (BAMLH0A0HYM2, BAMLC0A0CM, BAMLC0A4CBBB)
    #     is exclusively owned by K. X_REALIZED no longer reads OAS raw series.
    #     K_cp_bill_acceleration migrated to D_funding_acceleration_diagnostic.
    ProxySpec(
        name="K_credit_surface_HY_minus_IG",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"),
        raw_family="OAS_CREDIT",
        independence_group="credit_surface",
        mechanism="credit_surface_slope",
        transform="HY OAS minus IG OAS, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(
            _spread(p, "FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"),
            freq="daily",
        ),
        note="Daily credit surface slope. Available 2023-05-05+; gives K a true "
             "non-derivative day-frequency reading post-2023.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "Credit-spread slope. Finance-2.tex §4.4 explicitly excludes "
            "credit interpretation of K: K is options-derived IV/jump/tail. "
            "Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="K_credit_surface_BBB_minus_IG",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("FRED:BAMLC0A4CBBB", "FRED:BAMLC0A0CM"),
        raw_family="OAS_CREDIT",
        independence_group="credit_surface",
        mechanism="credit_surface_internal_curvature",
        transform="BBB OAS minus IG OAS, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(
            _spread(p, "FRED:BAMLC0A4CBBB", "FRED:BAMLC0A0CM"),
            freq="daily",
        ),
        note="Captures internal IG-grade curvature: when BBB compresses or "
             "blows out relative to IG composite, the credit surface deforms.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "BBB-IG credit spread, not transition-map curvature. Red-line "
            "violation (§4.4). Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="K_credit_surface_acceleration",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"),
        raw_family="OAS_CREDIT",
        independence_group="credit_surface",
        mechanism="credit_surface_nonlinear_break",
        transform="abs second-difference of HY-IG slope (5d), daily 21d mean, daily z-score",
        builder=lambda p: _component(
            _accel_abs(_spread(p, "FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"), periods=5),
            freq="daily",
        ),
        note="Δ² captures sudden curvature breaks (the kink, not the level). "
             "Designed to fire during regime changes like COVID-3-2020 / SVB-3-2023. "
             "v2: allow_derivative_reuse removed — intra-channel derivatives are fine; "
             "the flag only matters for cross-channel sharing which no longer occurs.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "Δ² of HY-IG is credit-spread acceleration, not IV-surface "
            "curvature. Red-line violation (§4.4). Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="K_baa10ym_level",
        target_variable="K",
        tier="auxiliary",  # Phase 2: demoted from core (历史长但月频, 让位给日频 OAS surface)
        freq="monthly",
        raw_series=("FRED:BAA10YM",),
        raw_family="FRED_CREDIT_LEVEL",
        independence_group="credit_surface",
        mechanism="credit_curve_deformation",
        transform="BAA-10Y spread level (monthly), 12-month rolling z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "FRED:BAA10YM", limit=35), freq="monthly"),
        note="K_HISTORICAL: long-history (1953+) credit-spread anchor. Auxiliary "
             "after Phase 2 — used as fallback when daily OAS surface is unavailable.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "BAA-10Y is a credit-curve level, not transition-map curvature. "
            "Red-line violation (§4.4). Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="K_baa10ym_delta",
        target_variable="K",
        tier="auxiliary",  # Phase 2: demoted from core
        freq="monthly",
        raw_series=("FRED:BAA10YM",),
        raw_family="FRED_CREDIT_LEVEL",
        independence_group="cross_asset_curvature",
        mechanism="credit_curve_transition_speed",
        transform="absolute monthly Δ BAA-10Y (native-freq diff), monthly 12m z-score, ffill to daily",
        builder=lambda p: _component(
            _native_freq_diff_abs(_series(p, "FRED:BAA10YM", limit=35), freq="monthly", periods=1),
            freq="monthly",
        ),
        note="K_HISTORICAL: monthly BAA-10Y change. Auxiliary after Phase 2.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "Δ BAA-10Y is credit-spread velocity, not curvature. "
            "Quarantined 2026-05-18."
        ),
    ),

    # ── X_PRE (Shadow Accumulation) ──────────────────────────────────────────
    #
    # Phase 3 拆 NFCI 单家族:
    #   - 保留 X_PRE_leverage_trace (NFCILEVERAGE) 作为唯一 NFCI 投票
    #   - 新增 X_PRE_stlfsi_pre_signal (STLFSI4) 作为独立家族 weekly core
    #   - X_PRE_risk_trace (NFCIRISK) 降到 diagnostic_only (与 NFCILEVERAGE 同源)
    # 这样 X_PRE family 从 100% NFCI 降到 50% NFCI + 50% STLFSI。
    ProxySpec(
        name="X_PRE_leverage_trace",
        target_variable="X_PRE",
        tier="core",
        freq="weekly",
        raw_series=("FRED:NFCILEVERAGE",),
        raw_family="NFCI",
        independence_group="hidden_leverage",
        mechanism="hidden_leverage_trace",
        transform="NFCI leverage subindex, weekly 1y rolling z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "FRED:NFCILEVERAGE", limit=7), freq="weekly"),
        note="Sole NFCI voter for X_PRE. NFCIRISK demoted in Phase 3 (same family).",
        canonical_status="extension_beyond_canonical",
        canonical_alignment_note=(
            "Target X_PRE is not in canonical paper. The NFCILEVERAGE data "
            "is reused as a WEAK proxy in the new canonical X_agg channel "
            "(see X_agg_v2_hidden_leverage_WEAK below). This legacy entry "
            "is dormant under canonical voting."
        ),
    ),
    ProxySpec(
        name="X_PRE_stlfsi_pre_signal",
        target_variable="X_PRE",
        tier="core",
        freq="weekly",
        raw_series=("FRED:STLFSI4",),
        raw_family="STLFSI",
        independence_group="pre_realization_pressure",
        mechanism="independent_pre_realization_stress_index",
        transform="St. Louis Fed Financial Stress Index, weekly 1y rolling z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "FRED:STLFSI4", limit=7), freq="weekly"),
        note="Available 1993-12-31+. Independent stress-index family from NFCI. Breaks the X_PRE "
             "NFCI mono-family. Different methodology than NFCI (different component weighting / "
             "construction), so co-movement reflects real stress, not measurement reuse.",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "STLFSI4 is a broad financial-stress benchmark, not a hidden-leverage / "
            "OBS / shadow-funding indicator. Putting STLFSI4 into X creates the "
            "circular pattern where a benchmark is renamed as a structural channel. "
            "Red-line violation. Quarantined 2026-05-18."
        ),
    ),
    ProxySpec(
        name="X_PRE_risk_trace",
        target_variable="X_PRE",
        tier="diagnostic_only",  # Phase 3: 与 NFCILEVERAGE 同源,降级
        freq="weekly",
        raw_series=("FRED:NFCIRISK",),
        raw_family="NFCI",
        independence_group="hidden_leverage",
        mechanism="shadow_risk_accumulation_trace",
        transform="NFCI risk subindex, weekly 1y rolling z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "FRED:NFCIRISK", limit=7), freq="weekly"),
        note="Phase 3: demoted to diagnostic_only. Visible in audit but not voting; same NFCI "
             "family as X_PRE_leverage_trace, would inflate NFCI weight if both voted.",
        canonical_status="extension_beyond_canonical",
        canonical_alignment_note=(
            "Target X_PRE is not canonical. NFCIRISK is a benchmark subindex anyway."
        ),
    ),

    # ── X_REALIZED (Forced Realization) ──────────────────────────────────────
    #
    # Phase 4 拆为 OFFICIAL × MARKET 双族:
    #   OFFICIAL (H41_RESCUE) — 官方救助柜台被使用 (沉默 → 危机点亮)
    #   MARKET   (VIX_JUMP)    — 市场强制变现冲击 (跳跃日)
    # v2: OAS_JUMP proxies removed from X_REALIZED. BAMLH0A0HYM2/BAMLC0A0CM/
    #     BAMLC0A4CBBB are exclusively owned by K (credit_surface). OAS credit
    #     data entering X_REALIZED core was a core-contract violation — same
    #     credit-spread event counted twice (once as surface deformation K,
    #     once as forced realization X_REALIZED).
    #     X_REALIZED market leg is now VIX-only. MOVE / Treasury basis stress
    #     can be added later as independent families within volatility_jump
    #     and forced_liquidation_marker.
    #
    # ── OFFICIAL (H41_RESCUE) ──
    ProxySpec(
        name="X_REALIZED_primary_credit",
        target_variable="X_REALIZED",
        # Demoted to diagnostic_only: canonical voter is Pi_t_observable_primary_credit.
        # Keeping the entry preserves audit trail without colliding with the new CORE.
        tier="diagnostic_only",
        freq="sparse",
        raw_series=("H41:primary_credit",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="official_support_usage",
        transform="primary credit usage, log1p, expanding-max-normalized activation score (5d window)",
        builder=lambda p: _component(_series(p, "H41:primary_credit", limit=14), freq="sparse"),
        canonical_status="extension_beyond_canonical",
        canonical_alignment_note=(
            "Target X_REALIZED is not in canonical paper. The H41 primary "
            "credit data is reassigned to the Π_t observation layer "
            "(see Pi_t_observable_primary_credit below). Tier demoted to "
            "diagnostic_only to avoid CORE collision with the new Pi_t voter."
        ),
    ),
    ProxySpec(
        name="X_REALIZED_discount_window",
        target_variable="X_REALIZED",
        tier="diagnostic_only",  # demoted: canonical voter lives under Pi_t
        freq="sparse",
        raw_series=("H41:discount_window",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="official_support_usage",
        transform="discount window usage, log1p, expanding-max-normalized activation score",
        builder=lambda p: _component(_series(p, "H41:discount_window", limit=14), freq="sparse"),
        canonical_status="extension_beyond_canonical",
        canonical_alignment_note=(
            "Target X_REALIZED is not canonical. H41 discount-window data is "
            "reassigned to Pi_t_observable_discount_window. Tier demoted to "
            "diagnostic_only."
        ),
    ),
    ProxySpec(
        name="X_REALIZED_btfp",
        target_variable="X_REALIZED",
        tier="diagnostic_only",  # demoted
        freq="sparse",
        raw_series=("H41:btfp",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="post_2023_forced_realization_facility",
        transform="BTFP usage, log1p, expanding-max-normalized activation score",
        builder=lambda p: _component(_series(p, "H41:btfp", limit=14), freq="sparse"),
        canonical_status="extension_beyond_canonical",
        canonical_alignment_note=(
            "Target X_REALIZED is not canonical. H41 BTFP data is "
            "reassigned to Pi_t_observable_btfp. Tier demoted to diagnostic_only."
        ),
    ),
    # ── MARKET (forced realization without official rescue) ──
    # v2: OAS_JUMP removed — credit-spread shock detection is K's domain.
    #     VIX is the sole market-leg proxy for now. Coverage is thinner
    #     (VIX-only vs VIX+OAS) but cleaner: no double-counting of credit
    #     events across K and X_REALIZED.
    ProxySpec(
        name="X_REALIZED_vix_jump",
        target_variable="X_REALIZED",
        tier="core",
        freq="daily",
        raw_series=("FRED:VIXCLS",),
        raw_family="VIX_JUMP",
        independence_group="volatility_jump",
        mechanism="market_implied_volatility_shock",
        transform="|Δ VIX(1d)|, daily 21d mean, daily 252d z-score, positive part",
        builder=lambda p: _jump_activation_score(_series(p, "FRED:VIXCLS")),
        note="VIXCLS 1990-01+. Captures forced-deleveraging / unwind days that "
             "do not trigger official facilities (e.g. Volmageddon 2018, "
             "August 2024 carry unwind, Repo 2019 mid-day).",
        canonical_status="quarantined_drift",
        canonical_alignment_note=(
            "|Δ VIX| is market-implied volatility. Canonical X_agg has no "
            "volatility component (§7.2.3). Putting VIX_jump into X also "
            "violates K's §4.4 exclusion of vol. The expanding-max activation "
            "saturates at the 1.5–3.5 cap, which was the root cause of the "
            "'X_REALIZED dominates all events' artefact. Quarantined 2026-05-18."
        ),
    ),
    # ─────────────────────────────────────────────────────────────────────────
    # CANONICAL VOTING / AWAITING_DATA / Π_T OBSERVATION LAYER
    # Added 2026-05-18 per Finance-2.tex red-line repair.
    # See governance/canonical_proxy_spec.yaml for the spec.
    # ─────────────────────────────────────────────────────────────────────────

    # ── M canonical sub-baskets ──
    # M.m1_funding_anchor_gap is currently covered by the re-tagged
    # M_policy_bill_gap above. m2 and m3 require data not yet in harvester.
    ProxySpec(
        name="M_canonical_NOT_IMPLEMENTED_m2_verifiability_gap",
        target_variable="M",
        tier="core",
        freq="weekly",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="verifiability_gap",
        mechanism="reporting_lag_or_htm_aocig_gap",
        transform="(awaiting data: HTM/AOCI gap, reporting-lag indicators)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="M.m2_verifiability_gap",
        canonical_alignment_note=(
            "Canonical M m2 requires HTM/AOCI gap, accounting fair-value gap, "
            "or reporting-lag-vs-valuation-speed data. SEC filing_pulse is too "
            "coarse. Required for SVB-class events (canonical example in §7.3)."
        ),
    ),
    ProxySpec(
        name="M_canonical_NOT_IMPLEMENTED_m3_liquidation_gap",
        target_variable="M",
        tier="core",
        freq="daily",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="liquidation_gap",
        mechanism="etf_nav_or_cash_futures_basis_stress",
        transform="(awaiting data: ETF/NAV stress, Treasury cash-futures basis)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="M.m3_liquidation_gap",
        canonical_alignment_note=(
            "Canonical M m3 requires ETF premium/discount, closed-end fund "
            "discounts, or cash-vs-futures Treasury basis (liquidation side). "
            "None available in harvester today."
        ),
    ),

    # ── D canonical sub-baskets ──
    # D.w3_funding_access is covered by the three re-tagged D proxies above.
    # w1 (market depth) and w2 (hedge breadth) need TAQ / options data.
    ProxySpec(
        name="D_canonical_NOT_IMPLEMENTED_w1_market_depth",
        target_variable="D_contraction",
        tier="core",
        freq="daily",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="market_depth",
        mechanism="bid_ask_or_book_depth",
        transform="(awaiting data: inverse bid-ask spread, top-of-book depth)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="D.w1_market_depth",
        canonical_alignment_note="Needs TAQ or order-book data not in harvester.",
    ),
    ProxySpec(
        name="D_canonical_NOT_IMPLEMENTED_w2_hedge_breadth",
        target_variable="D_contraction",
        tier="core",
        freq="daily",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="hedge_breadth",
        mechanism="option_oi_breadth_or_cross_maturity",
        transform="(awaiting data: option OI breadth, cross-maturity substitution)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="D.w2_hedge_breadth",
        canonical_alignment_note="Needs options open-interest data not in harvester.",
    ),

    # ── K canonical sub-baskets ──
    # u1 (IV term twist) and u3 (tail convexity) are now wired from existing
    # CBOE data as candidate_pending_promotion (NON-voting until §7.2.2 +
    # independence checks pass). u2 (jump intensity) remains awaiting_data
    # (needs intraday/bipower). K still votes NaN today (no canonical_voting
    # K proxy yet) — but the canonical sub-baskets are no longer all dataless.
    ProxySpec(
        name="K_u1_iv_term_twist_candidate",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("CBOE:VIX9D", "CBOE:VIX3M", "CBOE:VIX6M"),
        raw_family="CBOE_IVTS",
        independence_group="iv_distortion",
        mechanism="iv_skew_smile_term_twist",
        transform="VIX term-structure butterfly (VIX9D - 2*VIX3M + VIX6M), daily rolling z-score",
        # Level-independent curvature of the IV term structure — a twist/distortion
        # measure, NOT a vol level. _butterfly returns None when the CBOE tenors
        # are absent from the panel, degrading gracefully like the old shell.
        builder=lambda p: _component(_butterfly(p, "CBOE:VIX9D", "CBOE:VIX3M", "CBOE:VIX6M"), freq="daily"),
        canonical_status="candidate_pending_promotion",
        canonical_subbasket="K.u1_iv_distortion",
        canonical_alignment_note=(
            "Phase 1 K wiring (data already in harvester, see "
            "governance/proxy_data_procurement_audit + canonical_proxy_spec.yaml). "
            "VIX term-structure butterfly is a level-independent twist/distortion "
            "measure (NOT a vol level — respects §4.4 'K is NOT VIX'). NOT YET "
            "canonical_voting: must first clear the §7.2.2 falsification gate "
            "(incremental OOS content beyond vol/jump/tail benchmarks) and the "
            "independence check vs M/D/X_agg. Visible in audit, contributes 0."
        ),
    ),
    ProxySpec(
        name="K_canonical_NOT_IMPLEMENTED_u2_jump_intensity",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="jump_intensity",
        mechanism="bipower_variation_or_realized_jump",
        transform="(awaiting data: bipower variation gap, realized jump count)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="K.u2_jump_intensity",
        canonical_alignment_note="Needs intraday price data for bipower variation.",
    ),
    ProxySpec(
        name="K_u3_tail_convexity_candidate",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("CBOE:SKEW",),
        raw_family="CBOE_SKEW",
        independence_group="tail_convexity",
        mechanism="otm_put_richness_or_crash_skew",
        transform="CBOE SKEW index (OTM put richness / crash skew), daily rolling z-score",
        # CBOE SKEW is the canonical OTM-put-richness / crash-skew measure
        # (u3 canonical_indicators). _series returns None when absent.
        builder=lambda p: _component(_series(p, "CBOE:SKEW"), freq="daily"),
        canonical_status="candidate_pending_promotion",
        canonical_subbasket="K.u3_tail_convexity",
        canonical_alignment_note=(
            "Phase 1 K wiring. CBOE SKEW is the canonical OTM-put-richness / "
            "crash-skew tail-convexity measure (Table 6 u3 indicators). NOT YET "
            "canonical_voting: pending §7.2.2 falsification gate + independence "
            "check vs M/D/X_agg. Visible in audit, contributes 0 to voting."
        ),
    ),

    # ── K canonical_voting MVP (CBOE-derived, §4.4 compliant) ─────────────
    # These proxies use options-derived CBOE data, satisfying §4.4's requirement
    # that K is IV/jump/tail, NOT credit-spread. Added 2026-06-02 to give K
    # its first canonical_voting proxies.
    ProxySpec(
        name="K_vix_term_structure_twist",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("CBOE:VIX9D", "CBOE:VIX3M", "CBOE:VIX6M"),
        raw_family="CBOE_IVTS",
        independence_group="iv_distortion",
        mechanism="iv_term_structure_twist",
        transform="VIX term-structure butterfly (VIX9D - 2*VIX3M + VIX6M), daily rolling z-score",
        builder=lambda p: _component(_butterfly(p, "CBOE:VIX9D", "CBOE:VIX3M", "CBOE:VIX6M"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u1_iv_distortion",
        canonical_alignment_note=(
            "Level-independent curvature of IV term structure. §4.4 compliant: "
            "options-derived, not credit-spread. MVP proxy for K.iv_distortion."
        ),
    ),
    ProxySpec(
        name="K_cboe_skew_tail",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("CBOE:SKEW",),
        raw_family="CBOE_SKEW",
        independence_group="tail_convexity",
        mechanism="otm_put_richness_crash_skew",
        transform="CBOE SKEW index, daily rolling z-score",
        builder=lambda p: _component(_series(p, "CBOE:SKEW"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u3_tail_convexity",
        canonical_alignment_note=(
            "CBOE SKEW is the canonical OTM-put-richness / crash-skew measure "
            "(Table 6 u3 indicators). §4.4 compliant: options-derived."
        ),
    ),
    ProxySpec(
        name="K_vvix_vol_of_vol",
        target_variable="K",
        tier="auxiliary",
        freq="daily",
        raw_series=("CBOE:VVIX",),
        raw_family="CBOE_VVIX",
        independence_group="tail_convexity",
        mechanism="vol_of_vol_instability",
        transform="VVIX (vol-of-vol), daily rolling z-score",
        builder=lambda p: _component(_series(p, "CBOE:VVIX"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u3_tail_convexity",
        canonical_alignment_note=(
            "VVIX measures implied volatility of VIX options — a direct "
            "tail-convexity / vol-of-vol signal. §4.4 compliant."
        ),
    ),

    # ── X_agg canonical sub-baskets ──
    ProxySpec(
        name="X_agg_v1_obs_to_assets_candidate",
        target_variable="X_agg",
        tier="core",
        freq="quarterly",
        raw_series=("SEC:OBS_DERIV_TO_ASSETS",),
        raw_family="SEC_OBS",
        independence_group="off_balance_sheet",
        mechanism="obs_to_assets_or_derivatives_notional",
        transform="quarterly aggregate derivatives-notional/assets, 5y rolling z-score (quarterly cadence)",
        # _series returns None when SEC:OBS_DERIV_TO_ASSETS is absent from the
        # panel (e.g. a harvester release predating Phase 1), so this degrades
        # gracefully to no contribution exactly like the old awaiting_data shell.
        builder=lambda p: _component(_series(p, "SEC:OBS_DERIV_TO_ASSETS", limit=100), freq="quarterly"),
        canonical_status="candidate_pending_promotion",
        canonical_subbasket="X_agg.v1_off_balance_sheet",
        canonical_alignment_note=(
            "Phase 1 interim per governance/x_agg_v1_obs_procurement_plan.md: "
            "aggregate derivatives-notional/assets over a large dealer-bank CIK "
            "basket from SEC XBRL companyconcept. NOT YET canonical_voting — "
            "promotion to canonical requires (a) the FFIEC Y-9C HC-L canonical "
            "source (Phase 2), (b) independence check vs M/D/K, and (c) §7.2.3 "
            "weighting resolution with v2/v3. Visible in audit, contributes 0 "
            "to channel voting until promoted."
        ),
    ),
    ProxySpec(
        name="X_agg_v2_nfcileverage_quarantined_redline",
        target_variable="X_agg",
        tier="auxiliary",
        freq="weekly",
        raw_series=("FRED:NFCILEVERAGE",),
        raw_family="NFCI",
        independence_group="hidden_leverage_canonical",
        mechanism="hidden_leverage_trace_weak",
        transform="NFCILEVERAGE subindex (quarantined — broad-composite red-line violation)",
        builder=lambda p: _component(_series(p, "FRED:NFCILEVERAGE", limit=7), freq="weekly"),
        canonical_status="quarantined_drift",
        canonical_subbasket="X_agg.v2_hidden_leverage",
        canonical_alignment_note=(
            "RED-LINE FIX 2026-05-31: NFCILEVERAGE is a sub-index of NFCI, a "
            "broad financial-conditions composite. X_agg's own core_contract "
            "lists `broad_financial_conditions_composite` as a forbidden_group, "
            "so this proxy cannot canonically vote on X_agg — yet it was the "
            "SOLE X_agg voter, meaning X_agg was voting on a proxy that breaks "
            "its own red line. Demoted from canonical_voting to quarantined_drift. "
            "Consequence (intended): X_agg now has zero canonical_voting proxies "
            "and honestly reports NOT_IMPLEMENTED until a clean v2 hidden-leverage "
            "source (OFR/FRBNY primary-dealer/margin) or the Phase-1 v1 candidate "
            "is promoted. Kept for audit; re-promotable only if re-mapped to a "
            "non-composite mechanism."
        ),
    ),
    ProxySpec(
        name="X_agg_canonical_NOT_IMPLEMENTED_v3_shadow_funding_substitution",
        target_variable="X_agg",
        tier="core",
        freq="weekly",
        raw_series=(),
        raw_family="NOT_IMPLEMENTED",
        independence_group="shadow_funding_substitution",
        mechanism="collateral_transformation_or_bilateral_liquidity",
        transform="(awaiting data: collateral transformation, bilateral liquidity)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="X_agg.v3_shadow_funding_substitution",
        canonical_alignment_note="Needs shadow-banking flow/funding data. Not in harvester.",
    ),

    # ── X_agg canonical_voting MVP (2026-06-02) ─────────────────────────
    # Parallel to K MVP: new canonical_voting proxies alongside existing candidates.
    ProxySpec(
        name="X_agg_off_balance_sheet_v1",
        target_variable="X_agg",
        tier="core",
        freq="quarterly",
        raw_series=("SEC:OBS_DERIV_TO_ASSETS",),
        raw_family="SEC_OBS",
        independence_group="off_balance_sheet",
        mechanism="obs_to_assets_or_derivatives_notional",
        transform="quarterly OBS/assets ratio, quarterly z-score, ffill to daily",
        builder=lambda p: _component(_series(p, "SEC:OBS_DERIV_TO_ASSETS", limit=100), freq="quarterly"),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.v1_off_balance_sheet",
        canonical_alignment_note=(
            "SEC OBS/assets derivatives-notional ratio. Quarterly frequency "
            "resampled to daily via _freq_aware_zscore. MVP proxy for "
            "X_agg.v1 off_balance_sheet sub-basket."
        ),
    ),
    ProxySpec(
        name="X_agg_hidden_leverage_ofr",
        target_variable="X_agg",
        tier="auxiliary",
        freq="daily",
        raw_series=("OFR_FSI",),
        raw_family="OFR_SYSTEMIC",
        independence_group="hidden_leverage_canonical",
        mechanism="systemic_leverage_stress",
        transform="OFR Financial Stress Index, daily rolling z-score",
        builder=lambda p: _component(_series(p, "OFR_FSI"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.v2_hidden_leverage",
        canonical_alignment_note=(
            "OFR FSI is a market-based systemic stress indicator (not a "
            "broad financial-conditions composite like NFCI). Provides "
            "hidden-leverage signal for X_agg.v2 sub-basket. Auxiliary tier."
        ),
    ),

    # ── X_agg Tier 1 alias mapping (2026-06-03) ────────────────────────
    # Additional Harvester series mapped to X_agg sub-baskets.
    # All are independent of M/D/K (not used by any other channel).
    ProxySpec(
        name="X_agg_v1_treasury_debt_pressure",
        target_variable="X_agg",
        tier="auxiliary",
        freq="daily",
        raw_series=("TREASURY:debt_to_penny:tot_pub_debt_out_amt",),
        raw_family="TREASURY_DEBT",
        independence_group="off_balance_sheet",
        mechanism="government_refinancing_pressure",
        transform="total public debt outstanding, daily rolling z-score",
        builder=lambda p: _component(_series(p, "TREASURY:debt_to_penny:tot_pub_debt_out_amt"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.v1_off_balance_sheet",
        canonical_alignment_note=(
            "Total public debt outstanding as refinancing pressure signal. "
            "Daily frequency — improves X_agg temporal precision vs quarterly SEC. "
            "Independent of M/D/K channels."
        ),
    ),
    ProxySpec(
        name="X_agg_v2_treasury_cash_balance",
        target_variable="X_agg",
        tier="auxiliary",
        freq="daily",
        raw_series=("TREASURY:daily_treasury_statement:open_today_bal",),
        raw_family="TREASURY_CASH",
        independence_group="hidden_leverage_canonical",
        mechanism="treasury_cash_balance_stress",
        transform="Treasury cash balance (open_today_bal), daily rolling z-score (inverted: low balance = stress)",
        builder=lambda p: _component(_series(p, "TREASURY:daily_treasury_statement:open_today_bal"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.v2_hidden_leverage",
        canonical_alignment_note=(
            "Treasury General Account cash balance. Low balance indicates "
            "fiscal stress / debt ceiling pressure. Daily frequency. "
            "Independent of M/D/K channels."
        ),
    ),
    ProxySpec(
        name="X_agg_v3_sofr_iorb_spread",
        target_variable="X_agg",
        tier="core",
        freq="daily",
        raw_series=("DERIVED:SOFR_IORB_SPREAD",),
        raw_family="DERIVED_FUNDING",
        independence_group="shadow_funding_substitution",
        mechanism="secured_funding_stress",
        transform="SOFR-IORB spread (positive = funding stress), daily rolling z-score",
        builder=lambda p: _component(_series(p, "DERIVED:SOFR_IORB_SPREAD"), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.v3_shadow_funding_substitution",
        canonical_alignment_note=(
            "SOFR-IORB spread measures secured funding market stress. "
            "When SOFR > IORB, money market funds drain reserves — "
            "a shadow funding mechanism. First v3 proxy with data. "
            "Daily frequency. Independent of M/D/K channels."
        ),
    ),

    # ── Π_t observation layer (NOT voting; downstream validation only) ──
    ProxySpec(
        name="Pi_t_observable_primary_credit",
        target_variable="Pi_t",
        tier="core",
        freq="sparse",
        raw_series=("H41:primary_credit",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="forced_realization_observable",
        transform="primary credit usage, log1p, expanding-max-normalized (Π_t observable)",
        builder=lambda p: _component(_series(p, "H41:primary_credit", limit=14), freq="sparse"),
        canonical_status="reassigned_to_pi_observable",
        canonical_subbasket="Pi_t.observable_official_facility",
        canonical_alignment_note=(
            "H41 primary credit is an OBSERVABLE of Π firing (forced "
            "realization happened), not a proxy for X_agg stock. Lives in "
            "Π_t observation layer for downstream validation only. "
            "Does NOT vote on any latent channel."
        ),
    ),
    ProxySpec(
        name="Pi_t_observable_discount_window",
        target_variable="Pi_t",
        tier="core",
        freq="sparse",
        raw_series=("H41:discount_window",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="forced_realization_observable",
        transform="discount window usage, log1p, expanding-max-normalized (Π_t observable)",
        builder=lambda p: _component(_series(p, "H41:discount_window", limit=14), freq="sparse"),
        canonical_status="reassigned_to_pi_observable",
        canonical_subbasket="Pi_t.observable_official_facility",
        canonical_alignment_note="Π_t observable; does not vote.",
    ),
    ProxySpec(
        name="Pi_t_observable_btfp",
        target_variable="Pi_t",
        tier="auxiliary",
        freq="sparse",
        raw_series=("H41:btfp",),
        raw_family="H41_RESCUE",
        independence_group="official_liquidity_facility",
        mechanism="forced_realization_observable",
        transform="BTFP usage, log1p, expanding-max-normalized (Π_t observable)",
        builder=lambda p: _component(_series(p, "H41:btfp", limit=14), freq="sparse"),
        canonical_status="reassigned_to_pi_observable",
        canonical_subbasket="Pi_t.observable_official_facility",
        canonical_alignment_note="Π_t observable (post-2023 facility); does not vote.",
    ),
]


def build_measurement_bundle(panel: pd.DataFrame) -> MeasurementBundle:
    """Build audited structural channels from registered proxy components.

    The output is intentionally path-oriented. VIX, HY OAS, TEDRATE, and broad
    stress indices remain available as benchmarks/controls, but they no longer
    define D/K/X structural channels.
    """
    component_values = pd.DataFrame(index=panel.index)
    registry_rows: list[dict] = []
    for spec in PROXY_REGISTRY:
        value = spec.builder(panel)
        available = value is not None and value.notna().any()
        if available:
            component_values[spec.name] = value
        registry_rows.append({
            "name": spec.name,
            "target_variable": spec.target_variable,
            "channel": spec.target_variable,  # legacy alias
            "tier": spec.tier,
            "role": spec.tier,  # legacy alias
            "freq": spec.freq,
            "raw_series": list(spec.raw_series),
            "raw_family": spec.raw_family,
            "independence_group": spec.independence_group,
            "mechanism": spec.mechanism,
            "transform": spec.transform,
            "allow_derivative_reuse": spec.allow_derivative_reuse,
            "available": bool(available),
            "note": spec.note,
        })

    channels = pd.DataFrame(index=panel.index)
    coverage = pd.DataFrame(index=panel.index)
    confidence = pd.DataFrame(index=panel.index)
    for ch in CHANNELS:
        # Canonical red-line gate (Finance-2.tex, see governance/canonical_proxy_spec.yaml):
        # a proxy votes on a channel only if BOTH conditions hold:
        #   1. tier ∈ {core, auxiliary}
        #   2. canonical_status == "canonical_voting"
        # All other statuses (quarantined_drift / awaiting_data /
        # reassigned_to_pi_observable / diagnostic_consistent /
        # extension_beyond_canonical / unevaluated) are visible to audit but
        # contribute nothing to the channel value.
        # If a channel has zero canonical_voting proxies, its value is NaN and
        # downstream consumers must read it as NOT_IMPLEMENTED.
        specs = [
            s for s in PROXY_REGISTRY
            if s.target_variable == ch
            and s.tier in ("core", "auxiliary")
            and s.canonical_status == "canonical_voting"
        ]
        present = [s for s in specs if s.name in component_values.columns]
        if not present:
            channels[ch] = np.nan
            coverage[ch] = 0.0
            confidence[ch] = coverage[ch].map(confidence_label)
            continue

        # Two aggregation modes:
        #   simple_mean   — used for single-mechanism channels (M / D / K /
        #                   X_PRE). The within-channel proxies measure the
        #                   same physical thing through different lenses;
        #                   their mean is the consensus z-score.
        #   family_or     — used for X_REALIZED whose proxies span genuinely
        #                   distinct mechanisms (OFFICIAL rescue vs MARKET
        #                   forced-sell). Within each raw_family take max
        #                   (any spec firing = family active), then mean
        #                   across families (more families active = more
        #                   confident the regime is forced realization).
        #                   Avoids OFFICIAL-vs-MARKET specs diluting each
        #                   other through simple averaging.
        var = VARIABLES.get(ch)
        use_family_or = bool(var and var.expected_freq == "mixed")

        if use_family_or:
            # Per-family max
            by_family: dict[str, list[str]] = {}
            for s in present:
                by_family.setdefault(s.raw_family, []).append(s.name)
            family_aggs = pd.DataFrame(index=panel.index)
            for fam, names_in_fam in by_family.items():
                family_aggs[fam] = component_values[names_in_fam].max(axis=1, skipna=True)
            # Time-aware family roster: a family is "in roster" only after
            # its first valid family-aggregate value. Coverage = families
            # active today / families in roster today.
            valid_fam = family_aggs.notna()
            in_roster_fam = valid_fam.cummax()
            n_in_roster_fam = in_roster_fam.sum(axis=1)
            channels[ch] = family_aggs.mean(axis=1, skipna=True)
            coverage[ch] = (valid_fam.sum(axis=1) / n_in_roster_fam.clip(lower=1)).fillna(0.0)
        else:
            names = [s.name for s in present]
            comp = component_values[names]
            valid = comp.notna()
            channels[ch] = comp.mean(axis=1, skipna=True)
            # Time-aware "in-roster" count: a proxy is considered enrolled
            # only after its first non-null observation. Coverage is then
            # valid_today / proxies_in_roster_today, not / total_proxies_ever.
            # This prevents future-dated proxies (e.g. OAS surface starting
            # 2023-05) from making earlier history appear under-covered when
            # the historically-correct fallback proxies were fully in use.
            in_roster = valid.cummax()
            n_in_roster = in_roster.sum(axis=1)
            coverage[ch] = (valid.sum(axis=1) / n_in_roster.clip(lower=1)).fillna(0.0)
        confidence[ch] = coverage[ch].map(confidence_label)

    semantic = SemanticRegistry(SEMANTIC_REGISTRY_PATH)
    registry_rows = [semantic.attach_metadata(row, row["target_variable"]) for row in registry_rows]
    audit = audit_measurement_layers(channels, component_values, registry_rows, panel)
    return MeasurementBundle(
        channels=channels.clip(-4, 4),
        components=component_values,
        coverage=coverage,
        confidence=confidence,
        registry=registry_rows,
        audit=audit,
    )


def confidence_label(value: float) -> str:
    if value >= 0.75:
        return "VALID_FULL"
    if value >= 0.50:
        return "VALID_PARTIAL"
    if value >= 0.25:
        return "DIAGNOSTIC_ONLY"
    return "INVALID"


def audit_measurement_layers(
    channels: pd.DataFrame,
    components: pd.DataFrame,
    registry_rows: list[dict],
    panel: pd.DataFrame,
) -> dict:
    """v2: hardened measurement audit with CORE/DIGANOSTIC tier enforcement.

    CORE raw-series sharing across channels → HARD_ERROR (blocks execution).
    allow_derivative_reuse no longer silences; emits AUTHORIZED_SHARED_DERIVATIVE.
    independence_group cross-channel sharing enforced for CORE tier.
    core_contract violations downgrade or fail based on tier.
    """
    available = [r for r in registry_rows if r["available"]]
    voting = [r for r in available if r["tier"] in ("core", "auxiliary")]
    core_rows = [r for r in available if r["tier"] == "core"]
    diagnostic_rows = [r for r in available if r["tier"] not in ("core", "auxiliary")]

    # ── 1) CORE raw-series isolation (HARD_ERROR) ──────────────────────────
    core_raw_channels: dict[str, set[str]] = {}
    core_raw_sharing: list[dict] = []
    for row in core_rows:
        for raw in row["raw_series"]:
            core_raw_channels.setdefault(raw, set()).add(row["target_variable"])
    for raw, channels_seen in core_raw_channels.items():
        if len(channels_seen) > 1:
            core_raw_sharing.append({
                "raw_series": raw,
                "channels": sorted(channels_seen),
                "severity": "HARD_ERROR",
                "message": f"CORE RAW-SERIES SHARING: {raw} appears in {sorted(channels_seen)}",
            })

    # ── 2) Authorized / diagnostic shared-source detection ──────────────────
    authorized_shared_derivative: list[dict] = []
    diagnostic_shared_source: list[dict] = []
    all_voting_raw: dict[str, set[str]] = {}
    for row in voting:
        for raw in row["raw_series"]:
            all_voting_raw.setdefault(raw, set()).add(row["target_variable"])
    # Check diagnostic rows against voting channels
    for row in diagnostic_rows:
        for raw in row["raw_series"]:
            if raw in all_voting_raw:
                voting_chs = all_voting_raw[raw] - {row["target_variable"]}
                if voting_chs:
                    diagnostic_shared_source.append({
                        "raw_series": raw,
                        "diagnostic_proxy": row["name"],
                        "diagnostic_channel": row["target_variable"],
                        "voting_channels": sorted(voting_chs),
                        "severity": "DIAGNOSTIC_SHARED_SOURCE",
                    })
    # allow_derivative_reuse → now emits AUTHORIZED, not silent
    for row in voting:
        if row.get("allow_derivative_reuse"):
            for raw in row["raw_series"]:
                if raw in all_voting_raw and len(all_voting_raw[raw]) > 1:
                    authorized_shared_derivative.append({
                        "raw_series": raw,
                        "channels": sorted(all_voting_raw[raw]),
                        "proxy": row["name"],
                        "tier": row["tier"],
                        "reason": "allow_derivative_reuse=True on proxy",
                        "severity": "AUTHORIZED_SHARED_DERIVATIVE",
                    })

    # ── 3) independence_group cross-channel enforcement ─────────────────────
    group_channels: dict[str, set[str]] = {}
    group_sharing: list[dict] = []
    for row in core_rows:
        g = row.get("independence_group", "")
        if not g:
            continue
        group_channels.setdefault(g, set()).add(row["target_variable"])
    for g, chs in group_channels.items():
        if len(chs) > 1:
            group_sharing.append({
                "independence_group": g,
                "channels": sorted(chs),
                "severity": "HARD_ERROR",
                "message": f"INDEPENDENCE_GROUP CROSSING: {g!r} in CORE of {sorted(chs)}",
            })

    # ── 4) core_contract violations ─────────────────────────────────────────
    core_contract_violations: list[dict] = []
    for row in core_rows + [r for r in voting if r["tier"] == "auxiliary"]:
        var = VARIABLES.get(row["target_variable"])
        if var is None or not var.core_contract:
            continue
        g = row.get("independence_group", "")
        if not g:
            continue
        allowed = set(var.core_contract.get("allowed_groups", ()))
        forbidden = set(var.core_contract.get("forbidden_groups", ()))
        if g in forbidden:
            core_contract_violations.append({
                "channel": row["target_variable"],
                "proxy": row["name"],
                "tier": row["tier"],
                "independence_group": g,
                "violation": "FORBIDDEN_GROUP",
                "message": f"{row['name']} (group={g!r}) violates {row['target_variable']} core_contract forbidden_groups",
            })
        elif allowed and g not in allowed:
            core_contract_violations.append({
                "channel": row["target_variable"],
                "proxy": row["name"],
                "tier": row["tier"],
                "independence_group": g,
                "violation": "UNLISTED_GROUP",
                "message": f"{row['name']} (group={g!r}) not in {row['target_variable']} core_contract allowed_groups",
            })

    # ── 5) Cross-channel statistics (unchanged from v1) ─────────────────────
    channel_corr = channels[CHANNELS].corr(min_periods=252).round(3).fillna(0.0)
    max_corr = 0.0
    if len(channel_corr) > 1:
        vals = channel_corr.where(~np.eye(len(channel_corr), dtype=bool)).abs().stack()
        max_corr = float(vals.max()) if not vals.empty else 0.0

    residual_uniqueness = compute_residual_uniqueness(channels, panel)
    pc1_variance = compute_pc1_variance(channels)
    vif = compute_vif(channels)
    family_concentration = compute_family_concentration(voting)
    derivative_contamination = compute_derivative_contamination(channels)
    sparsity_flag = compute_sparsity_flags(channels, registry_rows)
    contract_violations = compute_contract_violations(registry_rows)
    horizon_consistency = compute_horizon_consistency(registry_rows)

    # ── 6) Build warnings (v2: tier-aware severity) ─────────────────────────
    warnings: list[str] = []

    # HARD_ERROR — core raw-series sharing (blocks execution)
    hard_errors: list[str] = []
    for item in core_raw_sharing:
        hard_errors.append(item["message"])
    for item in group_sharing:
        hard_errors.append(item["message"])

    # AUTHORIZED (was silences; now visible)
    for item in authorized_shared_derivative:
        warnings.append(
            f"AUTHORIZED_SHARED_DERIVATIVE: {item['proxy']} ({item['tier']}) "
            f"shares raw_series={item['raw_series']!r} across {item['channels']}. "
            f"reason={item['reason']}"
        )

    # DIAGNOSTIC (info-level, always visible)
    for item in diagnostic_shared_source:
        warnings.append(
            f"DIAGNOSTIC_SHARED_SOURCE: {item['diagnostic_proxy']} "
            f"({item['diagnostic_channel']}, diagnostic) reads {item['raw_series']!r} "
            f"which also feeds {item['voting_channels']} voting."
        )

    # Core contract violations
    for v in core_contract_violations:
        warnings.append(f"CORE_CONTRACT_VIOLATION: {v['message']}")

    # Statistical warnings (unchanged thresholds)
    if max_corr >= 0.85:
        warnings.append("CHANNEL_COLLAPSE: pairwise channel correlation exceeds 0.85.")
    elif max_corr >= 0.70:
        warnings.append("CHANNEL_CORRELATION_WARNING: pairwise channel correlation exceeds 0.70.")
    if pc1_variance >= 0.75:
        warnings.append("SCALAR_REGRESSION: first principal component explains more than 75% of channel variance.")
    elif pc1_variance >= 0.65:
        warnings.append("PC1_DOMINANCE_WARNING: first principal component explains more than 65% of channel variance.")
    weak = [ch for ch, val in residual_uniqueness.items() if val < 0.20]
    if weak:
        warnings.append(f"RESIDUAL_UNIQUENESS_WEAK: {', '.join(weak)} residual uniqueness below 0.20.")

    # Family warnings
    for ch, fams in family_concentration.items():
        if not fams:
            continue
        top_family, top_share = max(fams.items(), key=lambda kv: kv[1])
        if top_share > 0.75:
            warnings.append(
                f"FAMILY_MONOCULTURE: {ch} is {top_share:.0%} sourced from raw_family={top_family!r}."
            )
    family_overlap_pairs: list[tuple[str, str, str]] = []
    for ch1 in CHANNELS:
        for ch2 in CHANNELS:
            if ch1 >= ch2:
                continue
            shared = set(family_concentration.get(ch1, {})) & set(family_concentration.get(ch2, {}))
            for fam in shared:
                if (
                    family_concentration[ch1][fam] >= 0.30
                    and family_concentration[ch2][fam] >= 0.30
                    and abs(channel_corr.loc[ch1, ch2]) > 0.40
                ):
                    family_overlap_pairs.append((ch1, ch2, fam))
    for ch1, ch2, fam in family_overlap_pairs:
        warnings.append(
            f"FAMILY_CONTAMINATION: {ch1} and {ch2} both depend on raw_family={fam!r} "
            f"with corr={channel_corr.loc[ch1, ch2]:.2f}."
        )
    for entry in derivative_contamination:
        warnings.append(
            f"DERIVATIVE_CONTAMINATION: {entry['channel']} ~ Δ^{entry['order']}({entry['source']}) "
            f"corr={entry['correlation']:.2f}."
        )
    for ch, info in sparsity_flag.items():
        if info["false_independence"]:
            warnings.append(
                f"SPARSITY_FALSE_INDEPENDENCE: {ch} non_zero_coverage={info['non_zero_coverage']:.2f}, "
                f"low cross-channel R^2 may be due to dormancy, not orthogonality."
            )
    for v in contract_violations:
        warnings.append(
            f"CONTRACT_VIOLATION: variable={v['variable']} expects freq={v['expected_freq']!r}, "
            f"but core proxy={v['proxy']!r} is freq={v['actual_freq']!r}."
        )
    for ch, info in horizon_consistency.items():
        if info.get("warning"):
            horizons_str = ", ".join(f"{f}×{n}" for f, n in info["horizons"].items())
            warnings.append(
                f"HORIZON_INCONSISTENT: {ch} (expected_freq={info['expected_freq']!r}) "
                f"mixes {info['n_freq_classes']} freq classes ({horizons_str}); "
                f"channel-mean aggregates unevenly across information-per-unit-time."
            )

    return {
        "hard_errors": hard_errors,
        "core_raw_sharing": core_raw_sharing,
        "independence_group_sharing": group_sharing,
        "authorized_shared_derivative": authorized_shared_derivative,
        "diagnostic_shared_source": diagnostic_shared_source,
        "core_contract_violations": core_contract_violations,
        "channel_correlation": channel_corr.to_dict(),
        "max_abs_channel_correlation": max_corr,
        "pc1_variance_share": pc1_variance,
        "vif": vif,
        "residual_uniqueness": residual_uniqueness,
        "family_concentration": family_concentration,
        "derivative_contamination": derivative_contamination,
        "sparsity_flag": sparsity_flag,
        "contract_violations": contract_violations,
        "horizon_consistency": horizon_consistency,
        "known_data_gaps": list(KNOWN_DATA_GAPS),
        "warnings": warnings,
    }


def compute_family_concentration(voting_rows: list[dict]) -> dict[str, dict[str, float]]:
    """Per-variable share of (core+aux) proxies coming from each raw_family.

    A variable whose proxies all come from one family has no sourcing diversity
    even if its proxies look numerous. Returns {}-shaped dict per channel.
    """
    counters: dict[str, dict[str, int]] = {ch: {} for ch in CHANNELS}
    for row in voting_rows:
        ch = row["target_variable"]
        fam = row.get("raw_family", "UNKNOWN")
        if ch not in counters:
            continue
        counters[ch][fam] = counters[ch].get(fam, 0) + 1
    out: dict[str, dict[str, float]] = {}
    for ch, fams in counters.items():
        total = sum(fams.values())
        if total == 0:
            out[ch] = {}
        else:
            out[ch] = {fam: round(n / total, 3) for fam, n in fams.items()}
    return out


def compute_derivative_contamination(channels: pd.DataFrame) -> list[dict]:
    """Check whether one channel is ≈ a finite-difference derivative of another.

    For each ordered pair (ch1, ch2) and order in {1, 2}, compute
    corr(channels[ch1], abs( channels[ch2].diff(periods=order) )) on the
    overlap window and flag if it exceeds 0.45.

    This catches K = Δ²(D) style relationships even when raw families differ.
    """
    findings: list[dict] = []
    for ch1 in CHANNELS:
        for ch2 in CHANNELS:
            if ch1 == ch2:
                continue
            for order in (1, 2):
                src = channels[ch2].diff(order).abs()
                joint = pd.concat([channels[ch1], src], axis=1).dropna()
                if len(joint) < 252:
                    continue
                corr = float(joint.iloc[:, 0].corr(joint.iloc[:, 1]))
                if abs(corr) > 0.45:
                    findings.append({
                        "channel": ch1,
                        "source": ch2,
                        "order": order,
                        "correlation": round(corr, 3),
                    })
    return findings


def compute_sparsity_flags(channels: pd.DataFrame, registry_rows: list[dict]) -> dict[str, dict]:
    """Flag channels whose statistical independence is sparsity-driven.

    For each channel, compute:
      - coverage_total: fraction of days with non-NaN channel value
      - non_zero_coverage: fraction of (covered) days with |z| > 0.1
      - flag: True iff non_zero_coverage < 0.20 (i.e. mostly silent)
    """
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        if ch not in channels.columns:
            out[ch] = {"non_zero_coverage": 0.0, "false_independence": False}
            continue
        s = channels[ch]
        covered = s.notna()
        total = int(covered.sum())
        if total == 0:
            out[ch] = {"non_zero_coverage": 0.0, "false_independence": False}
            continue
        non_zero = (s.abs() > 0.1) & covered
        non_zero_cov = float(non_zero.sum() / total)
        out[ch] = {
            "covered_days": total,
            "non_zero_coverage": round(non_zero_cov, 3),
            "false_independence": non_zero_cov < 0.20,
        }
    return out


def compute_horizon_consistency(registry_rows: list[dict]) -> dict:
    """Per-variable horizon distribution + warning if mixed-frequency aggregation.

    A channel whose voting proxies span multiple frequencies (daily + weekly +
    monthly) implicitly weights spec contributions unevenly along the time
    axis: a daily proxy contributes a fresh value every business day, a
    weekly proxy contributes the same value 5x, a monthly proxy 21x. Simple-
    mean aggregation thus over-weights low-frequency specs in information-
    per-unit-time terms.

    A variable can legitimately span horizons (X_REALIZED's OFFICIAL+MARKET
    design needs both sparse and daily); these declare expected_freq='mixed'
    and are not flagged. Variables with a single nominal expected_freq that
    accumulate cross-horizon proxies via fallback (K daily OAS + monthly
    BAA10YM) are flagged so the operator knows the channel value is a
    cross-frequency mix.
    """
    import collections as _coll
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        voting = [
            r for r in registry_rows
            if r.get("target_variable") == ch
            and r.get("tier") in ("core", "auxiliary")
            and r.get("available")
        ]
        if not voting:
            out[ch] = {"horizons": {}, "n_freq_classes": 0, "warning": False}
            continue
        freq_counter = _coll.Counter(r.get("freq", "unknown") for r in voting)
        n_classes = len(freq_counter)
        var = VARIABLES.get(ch)
        legitimately_mixed = bool(var and var.expected_freq == "mixed")
        # Mixing primary expected_freq with declared historical_fallback_freqs
        # is a legitimate design choice (e.g. K daily OAS + monthly BAA10YM).
        accepted = set()
        if var:
            accepted.add(var.expected_freq)
            accepted.update(var.historical_fallback_freqs)
        observed = set(freq_counter)
        within_contract = bool(accepted) and observed.issubset(accepted)
        warn = (n_classes > 1) and (not legitimately_mixed) and (not within_contract)
        out[ch] = {
            "horizons": dict(freq_counter),
            "n_freq_classes": n_classes,
            "expected_freq": var.expected_freq if var else None,
            "accepted_fallback_freqs": list(var.historical_fallback_freqs) if var else [],
            "legitimately_mixed": legitimately_mixed,
            "within_fallback_contract": within_contract,
            "warning": warn,
        }
    return out


def compute_realized_activation_quality(
    channels: pd.DataFrame,
    components: pd.DataFrame,
    registry_rows: list[dict],
    events: list[dict],
    thresholds: dict[str, dict[str, float]],
) -> dict:
    """Activation-quality audit for X_REALIZED.

    Per your Phase 4 brief: don't only look at correlation. Ask:
      activation_recall   — in events that did force realization
                            (rescue OR market jump), did X_REALIZED fire?
      false_activation_rate — outside any known event window, how often
                              does X_REALIZED still cross its warning?
      first_trigger_lead — for events that did fire, how many days
                            before peak did the first trigger occur?
      sub_family_split   — within X_REALIZED, what share of activation
                            came from OFFICIAL (H41_RESCUE) vs MARKET
                            (VIX_JUMP / OAS_JUMP)?

    Activation = X_REALIZED z >= warning threshold.
    """
    if "X_REALIZED" not in channels.columns:
        return {}
    x = channels["X_REALIZED"]
    warn = thresholds.get("X_REALIZED", {}).get("warning", 1.0)
    critical = thresholds.get("X_REALIZED", {}).get("critical", 1.5)

    per_event: list[dict] = []
    for ev in events:
        peak = pd.Timestamp(ev["peak"])
        win_start = peak - pd.Timedelta(days=120)
        win_end = peak + pd.Timedelta(days=30)
        window = x[(x.index >= win_start) & (x.index <= win_end)]
        valid_window = window.dropna()
        if valid_window.empty:
            per_event.append({
                "event_id": ev["id"],
                "event_name": ev["name"],
                "activated": None,
                "reason": "no_data",
            })
            continue
        triggered = valid_window[valid_window >= warn]
        activated = bool(not triggered.empty)
        first_lead = None
        peak_val = None
        if activated:
            first_lead = int((triggered.index[0] - peak).days)
            peak_val = float(valid_window.max())
        per_event.append({
            "event_id": ev["id"],
            "event_name": ev["name"],
            "activated": activated,
            "first_trigger_lead_days": first_lead,
            "peak_window_max": peak_val,
        })

    n_with_data = sum(1 for e in per_event if e["activated"] is not None)
    n_activated = sum(1 for e in per_event if e["activated"])
    recall = (n_activated / n_with_data) if n_with_data else 0.0

    # False-activation rates over calm days (outside any STRESS_EVENTS pre→post
    # window). We report at BOTH warning and critical thresholds:
    #   warning (90th pctile): inclusive — minor market shocks not on the
    #                          STRESS_EVENTS list (e.g. Asian crisis 1997,
    #                          Russia 1998 outside the official LTCM window,
    #                          WorldCom 2002, Brexit 2016) trigger here. A
    #                          high warning false_rate often means the event
    #                          list is incomplete, not that the channel is
    #                          mis-firing.
    #   critical (95th pctile): semantic — "true" forced-realization-grade
    #                           activation. False rate at critical is the
    #                           more honest measurement of channel quality.
    in_event = pd.Series(False, index=x.index)
    for ev in events:
        e_start = pd.Timestamp(ev["pre_start"])
        e_end = pd.Timestamp(ev["post_end"])
        in_event |= (x.index >= e_start) & (x.index <= e_end)
    calm_idx = (~in_event) & x.notna()
    calm_days = int(calm_idx.sum())
    calm_activated_warn = int(((x >= warn) & calm_idx).sum())
    calm_activated_crit = int(((x >= critical) & calm_idx).sum())
    false_rate_warn = (calm_activated_warn / calm_days) if calm_days else 0.0
    false_rate_crit = (calm_activated_crit / calm_days) if calm_days else 0.0
    # Default `false_activation_rate` reports the critical-threshold rate so
    # cross-Phase comparisons are not contaminated by threshold drift.
    calm_activated = calm_activated_crit
    false_rate = false_rate_crit

    # Sub-family split: where does activation come from?
    family_for_spec = {
        r["name"]: r.get("raw_family", "UNKNOWN")
        for r in registry_rows
        if r.get("target_variable") == "X_REALIZED"
        and r.get("tier") in ("core", "auxiliary")
        and r.get("available")
    }
    sub_aggregates: dict[str, dict] = {}
    for fam in set(family_for_spec.values()):
        cols = [name for name, f in family_for_spec.items() if f == fam and name in components.columns]
        if not cols:
            continue
        sub = components[cols].mean(axis=1, skipna=True)
        valid_count = int(sub.notna().sum())
        active_count = int((sub >= warn).sum())
        in_event_mask = in_event.reindex(sub.index, fill_value=False)
        active_in_event = int(((sub >= warn) & in_event_mask).sum())
        active_calm = int(((sub >= warn) & ~in_event_mask & sub.notna()).sum())
        sub_aggregates[fam] = {
            "n_voting_proxies": len(cols),
            "voting_proxies": cols,
            "valid_days": valid_count,
            "active_days_total": active_count,
            "active_days_in_event_window": active_in_event,
            "active_days_calm": active_calm,
        }

    return {
        "warning_threshold": float(warn),
        "critical_threshold": float(critical),
        "events_with_data": n_with_data,
        "events_activated": n_activated,
        "activation_recall": round(recall, 3),
        "false_activation_rate": round(false_rate, 4),
        "false_activation_rate_at_warning": round(false_rate_warn, 4),
        "false_activation_rate_at_critical": round(false_rate_crit, 4),
        "calm_days": calm_days,
        "calm_activated_days": calm_activated,
        "calm_activated_at_warning": calm_activated_warn,
        "calm_activated_at_critical": calm_activated_crit,
        "per_event": per_event,
        "sub_family_split": sub_aggregates,
    }


def compute_contract_violations(registry_rows: list[dict]) -> list[dict]:
    """Compare each available core proxy's freq to its variable's expected_freq.

    Rules:
      daily       → accepts daily core only.
      weekly      → accepts weekly or daily core.
      monthly     → accepts monthly, weekly, or daily core.
      sparse      → accepts sparse core only.
      mixed       → accepts any (sparse + daily/weekly OK by design;
                     used for variables with multi-mode activation logic
                     such as X_REALIZED = OFFICIAL (sparse) ∪ MARKET (daily)).
    """
    violations: list[dict] = []
    rank = {"daily": 3, "weekly": 2, "monthly": 1, "sparse": 0, "mixed": -1}
    for row in registry_rows:
        if not row.get("available"):
            continue
        if row.get("tier") != "core":
            continue
        var = VARIABLES.get(row["target_variable"])
        if var is None:
            continue
        actual = row.get("freq")
        expected = var.expected_freq
        if expected == "mixed":
            ok = True
        elif expected == "sparse":
            ok = actual == "sparse"
        else:
            ok = actual != "sparse" and rank.get(actual, -1) >= rank.get(expected, -1)
        if not ok:
            violations.append({
                "variable": row["target_variable"],
                "expected_freq": expected,
                "proxy": row["name"],
                "actual_freq": actual,
            })
    return violations


def compute_pc1_variance(channels: pd.DataFrame) -> float:
    clean = channels[CHANNELS].dropna(how="any")
    if len(clean) < 252 or clean.shape[1] < 2:
        return 0.0
    x = clean - clean.mean()
    cov = np.cov(x.to_numpy(), rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    total = eigvals.sum()
    if total <= 0:
        return 0.0
    return float(eigvals.max() / total)


def compute_vif(channels: pd.DataFrame) -> dict[str, float]:
    # Only compute VIF for channels that actually have data.
    active_channels = [ch for ch in CHANNELS if ch in channels.columns and channels[ch].notna().any()]
    if len(active_channels) < 2:
        return {ch: 0.0 for ch in CHANNELS}
    clean = channels[active_channels].dropna(how="any")
    result: dict[str, float] = {}
    if len(clean) < 252:
        return {ch: 0.0 for ch in CHANNELS}
    for ch in active_channels:
        y = clean[ch].to_numpy()
        others = [c for c in active_channels if c != ch]
        x = clean[others].to_numpy()
        x = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        ss_res = float(((y - pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 0.0 if ss_tot == 0 else max(0.0, min(0.999, 1 - ss_res / ss_tot))
        result[ch] = float(1 / (1 - r2))
    # Fill inactive channels with 0.0
    for ch in CHANNELS:
        result.setdefault(ch, 0.0)
    return result


def compute_residual_uniqueness(channels: pd.DataFrame, panel: pd.DataFrame) -> dict[str, float]:
    # Only compute for channels that actually have data.
    active_channels = [ch for ch in CHANNELS if ch in channels.columns and channels[ch].notna().any()]
    if len(active_channels) < 2:
        return {ch: 0.0 for ch in CHANNELS}
    data = channels[active_channels].copy()
    vix = _series(panel, "FRED:VIXCLS")
    if vix is not None:
        data["VIX_control"] = _rolling_zscore(vix)
    clean = data.dropna(how="any")
    result: dict[str, float] = {}
    if len(clean) < 252:
        return {ch: 0.0 for ch in CHANNELS}
    for ch in active_channels:
        y = clean[ch].to_numpy()
        controls = [c for c in clean.columns if c != ch]
        x = clean[controls].to_numpy()
        x = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        ss_res = float(((y - pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 0.0 if ss_tot == 0 else max(0.0, min(1.0, 1 - ss_res / ss_tot))
        result[ch] = float(max(0.0, 1 - r2))
    # Fill inactive channels with 0.0
    for ch in CHANNELS:
        result.setdefault(ch, 0.0)
    return result


# ── Benchmark Signals ────────────────────────────────────────────────────────

def build_benchmark_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """Build benchmark stress signals from standard indicators."""
    signals = pd.DataFrame(index=panel.index)

    # VIX
    if "FRED:VIXCLS" in panel.columns:
        vix = panel["FRED:VIXCLS"].interpolate(limit=5)
        mu = vix.expanding(252).mean()
        sigma = vix.expanding(252).std().replace(0, 1)
        signals["VIX_zscore"] = ((vix - mu) / sigma).clip(-3, 5)

    # NFCI
    if "FRED:NFCI" in panel.columns:
        nfci = panel["FRED:NFCI"].interpolate(limit=7)
        mu = nfci.expanding(252).mean()
        sigma = nfci.expanding(252).std().replace(0, 1)
        signals["NFCI_zscore"] = ((nfci - mu) / sigma).clip(-3, 5)

    # STLFSI4
    if "FRED:STLFSI4" in panel.columns:
        stlfsi = panel["FRED:STLFSI4"].interpolate(limit=7)
        mu = stlfsi.expanding(252).mean()
        sigma = stlfsi.expanding(252).std().replace(0, 1)
        signals["STLFSI4_zscore"] = ((stlfsi - mu) / sigma).clip(-3, 5)

    # BAA10YM (credit spread)
    if "FRED:BAA10YM" in panel.columns:
        baa10 = panel["FRED:BAA10YM"].interpolate(limit=5)
        mu = baa10.expanding(252).mean()
        sigma = baa10.expanding(252).std().replace(0, 1)
        signals["BAA10YM_zscore"] = ((baa10 - mu) / sigma).clip(-3, 5)

    # HY OAS (where available)
    if "FRED:BAMLH0A0HYM2" in panel.columns:
        hy = panel["FRED:BAMLH0A0HYM2"].interpolate(limit=5)
        mu = hy.expanding(252).mean()
        sigma = hy.expanding(252).std().replace(0, 1)
        signals["HYOAS_zscore"] = ((hy - mu) / sigma).clip(-3, 5)

    # TEDRATE (retired, but available pre-2022)
    if "FRED:TEDRATE" in panel.columns:
        ted = panel["FRED:TEDRATE"].interpolate(limit=5)
        mu = ted.expanding(252).mean()
        sigma = ted.expanding(252).std().replace(0, 1)
        signals["TEDRATE_zscore"] = ((ted - mu) / sigma).clip(-3, 5)

    # CP-Bill spread
    if "FRED:DCPF3M" in panel.columns and "FRED:DGS3MO" in panel.columns:
        cp_bill = panel["FRED:DCPF3M"] - panel["FRED:DGS3MO"]
        mu = cp_bill.expanding(252).mean()
        sigma = cp_bill.expanding(252).std().replace(0, 1)
        signals["CPBill_zscore"] = ((cp_bill - mu) / sigma).clip(-3, 5)

    # NFCI sub-indices
    for sub in ["NFCIRISK", "NFCILEVERAGE", "NFCICREDIT"]:
        col = f"FRED:{sub}"
        if col in panel.columns:
            s = panel[col].interpolate(limit=7)
            mu = s.expanding(252).mean()
            sigma = s.expanding(252).std().replace(0, 1)
            signals[f"{sub}_zscore"] = ((s - mu) / sigma).clip(-3, 5)

    return signals


# ── Event Analysis ───────────────────────────────────────────────────────────

@dataclass
class EventResult:
    event_id: str
    event_name: str
    peak_date: str
    category: str
    observed_path: list[dict] = field(default_factory=list)
    path_text: str = ""
    peak_regime: str = ""
    channel_at_peak: dict[str, float] = field(default_factory=dict)
    channel_coverage_at_peak: dict[str, float] = field(default_factory=dict)
    channel_confidence_at_peak: dict[str, str] = field(default_factory=dict)
    first_trigger_dates: dict[str, str] = field(default_factory=dict)
    benchmark_context: dict[str, float] = field(default_factory=dict)
    governance_flags: list[str] = field(default_factory=list)
    data_available: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def calibrate_path_thresholds(channels: pd.DataFrame) -> dict[str, dict[str, float]]:
    train = channels[(channels.index >= "2007-01-01") & (channels.index <= "2016-12-31")]
    if len(train.dropna(how="all")) < 252:
        train = channels
    thresholds: dict[str, dict[str, float]] = {}
    for ch in CHANNELS:
        s = train[ch].dropna() if ch in train.columns else pd.Series(dtype=float)
        if len(s) < 30:
            thresholds[ch] = {"warning": 1.0, "critical": 1.5}
            continue
        thresholds[ch] = {
            "warning": float(s.quantile(0.90)),
            "critical": float(s.quantile(0.95)),
        }
    return thresholds


def classify_regime(row: pd.Series, thresholds: dict[str, dict[str, float]], confidence: dict[str, str]) -> str:
    active = {ch: bool(row.get(ch, np.nan) >= thresholds[ch]["warning"]) for ch in CHANNELS}
    # Only flag "Measurement Blind Spot" if a channel that SHOULD have data
    # is INVALID.  Channels that are never implemented (X_PRE, X_REALIZED, Pi_t)
    # are expected to be INVALID and should not block classification.
    implemented_channels = {"M", "D_contraction", "K", "X_agg"}
    blind = any(
        confidence.get(ch) == "INVALID"
        for ch in implemented_channels
        if ch in confidence
    )
    if blind:
        return "Measurement Blind Spot"
    if active.get("X_REALIZED"):
        return "Forced Realization"
    if active.get("K") and active.get("D_contraction"):
        return "Curvature Break"
    if active.get("D_contraction"):
        return "Path Compression"
    if active.get("M"):
        return "Anchor Drift"
    if active.get("X_PRE"):
        return "Shadow Accumulation Trace"
    return "Normal / Untriggered"


def analyze_event(
    ev: dict,
    benchmarks: pd.DataFrame,
    bundle: MeasurementBundle,
    thresholds: dict[str, dict[str, float]],
) -> EventResult:
    r = EventResult(
        event_id=ev["id"], event_name=ev["name"],
        peak_date=ev["peak"], category=ev["category"],
    )
    peak = pd.Timestamp(ev["peak"])
    event_start = pd.Timestamp(ev["start"])
    event_end = pd.Timestamp(ev["end"])
    pre_window_start = peak - pd.Timedelta(days=120)

    channels = bundle.channels
    coverage = bundle.coverage
    confidence = bundle.confidence
    if not channels.empty:
        idx = np.argmin(np.abs((channels.index - peak).total_seconds().values))
        peak_date = channels.index[idx]
        row = channels.iloc[idx]
        cov_row = coverage.iloc[idx]
        conf_row = confidence.iloc[idx]
        r.channel_at_peak = {
            ch: float(row[ch]) for ch in CHANNELS if ch in row.index and pd.notna(row[ch])
        }
        r.channel_coverage_at_peak = {
            ch: float(cov_row[ch]) for ch in CHANNELS if ch in cov_row.index and pd.notna(cov_row[ch])
        }
        r.channel_confidence_at_peak = {
            ch: str(conf_row[ch]) for ch in CHANNELS if ch in conf_row.index
        }
        r.peak_regime = classify_regime(row, thresholds, r.channel_confidence_at_peak)

        for ch in CHANNELS:
            if ch not in channels.columns:
                r.data_available[ch] = False
                continue
            series = channels[ch].dropna()
            r.data_available[ch] = not series.empty
            window = series[(series.index >= pre_window_start) & (series.index <= event_end)]
            trigger = window[window >= thresholds[ch]["warning"]]
            if not trigger.empty:
                date = trigger.index[0]
                r.first_trigger_dates[ch] = date.date().isoformat()
                r.observed_path.append({
                    "channel": ch,
                    "date": date.date().isoformat(),
                    "days_before_peak": int((peak - date).days),
                    "value": float(trigger.iloc[0]),
                    "threshold": thresholds[ch]["warning"],
                })
        r.observed_path = sorted(r.observed_path, key=lambda x: x["date"])
        r.path_text = " -> ".join(item["channel"] for item in r.observed_path) or "no structural channel crossed warning threshold"

    for sig in ["VIX_zscore", "NFCI_zscore", "STLFSI4_zscore", "BAA10YM_zscore", "HYOAS_zscore", "CPBill_zscore"]:
        if sig not in benchmarks.columns:
            continue
        s = benchmarks[sig].dropna()
        win = s[(s.index >= event_start - pd.Timedelta(days=30)) & (s.index <= event_end)]
        if not win.empty:
            r.benchmark_context[sig] = float(win.max())

    r.governance_flags = list(bundle.audit.get("warnings", []))

    # Notes
    if peak > pd.Timestamp("2022-01-22"):
        r.notes.append("TEDRATE retired Jan 2022; retained only as historical benchmark where available.")
    if peak < pd.Timestamp("2023-05-01"):
        r.notes.append("Cached HY OAS starts in 2023; BAA10YM is the public credit-curve proxy for earlier windows.")
    if r.channel_confidence_at_peak.get("X_PRE") in ("INVALID", "DIAGNOSTIC_ONLY"):
        r.notes.append("X_PRE is weakly observed; do not interpret missing X_PRE movement as absence of hidden accumulation.")

    return r


def check_calm_contamination(results: list[EventResult], events: list[dict]) -> dict:
    event_dates = {e["id"]: (pd.Timestamp(e["start"]), pd.Timestamp(e["end"])) for e in events}
    contamination = {}
    for r in results:
        pre_start = pd.Timestamp(next(e["pre_start"] for e in events if e["id"] == r.event_id))
        calm_end = pre_start - pd.Timedelta(days=30)
        calm_start = calm_end - pd.Timedelta(days=90)
        for eid, (estart, eend) in event_dates.items():
            if eid == r.event_id:
                continue
            if calm_start <= eend and calm_end >= estart:
                contamination[r.event_id] = f"overlaps with '{eid}'"
                break
        else:
            contamination[r.event_id] = "clean"
    return contamination


# ── Report ───────────────────────────────────────────────────────────────────

def generate_report(
    results: list[EventResult],
    bundle: MeasurementBundle,
    thresholds: dict[str, dict[str, float]],
    calm_contamination: dict,
) -> str:
    lines = [
        "# Structural Deformation System — Path Replay v0.3",
        "",
        f"**Generated:** {pd.Timestamp.now().isoformat()}",
        f"**Events:** {len(results)}",
        f"**Data:** Harvester official panel 2026-05-05-r1 (27 series, 236K rows)",
        "**Proxy:** audited M/D/K/X_PRE/X_REALIZED measurement layer",
        "**Interpretation rule:** outputs are path diagnostics, not optimized scalar targets.",
        "",
        "---",
        "",
        "## 1. Measurement Boundary",
        "",
        "- VIX, HY OAS, TEDRATE, STLFSI4, and NFCI composite remain benchmark/context signals; they do not define structural D/K/X channels.",
        "- `X_PRE` and `X_REALIZED` are separate. Official support usage is treated as forced realization, not hidden accumulation.",
        "- Thresholds are training-window path triggers used to describe channel sequence; they are not a reward target.",
        "",
        "### Path Trigger Thresholds",
        "",
        "| Channel | Warning Trigger | Critical Trigger |",
        "|---|---:|---:|",
    ]
    for ch in CHANNELS:
        lines.append(f"| {ch} | {thresholds[ch]['warning']:.3f} | {thresholds[ch]['critical']:.3f} |")

    lines += [
        "---",
        "",
        "## 2. Measurement Governance",
        "",
        f"**Max absolute channel correlation:** {bundle.audit['max_abs_channel_correlation']:.3f}",
        f"**PC1 variance share:** {bundle.audit['pc1_variance_share']:.3f}",
        "",
        "| Channel | Residual Uniqueness | VIF |",
        "|---|---:|---:|",
    ]
    for ch in CHANNELS:
        ru = bundle.audit["residual_uniqueness"].get(ch, 0.0)
        vif = bundle.audit["vif"].get(ch, 0.0)
        lines.append(f"| {ch} | {ru:.3f} | {vif:.2f} |")

    # v2: independence enforcement report
    raw_sharing = bundle.audit.get("core_raw_sharing", [])
    group_sharing = bundle.audit.get("independence_group_sharing", [])
    authorized = bundle.audit.get("authorized_shared_derivative", [])
    diagnostic_shared = bundle.audit.get("diagnostic_shared_source", [])
    contract_vios = bundle.audit.get("core_contract_violations", [])
    hard_errs = bundle.audit.get("hard_errors", [])

    lines += [
        "",
        "### v2 Core Isolation Enforcement",
        "",
        f"**HARD_ERROR count:** {len(hard_errs)}",
        f"**Core raw-series sharing violations:** {len(raw_sharing)}",
        f"**Independence-group crossings:** {len(group_sharing)}",
        f"**Authorized shared derivatives:** {len(authorized)}",
        f"**Diagnostic shared sources:** {len(diagnostic_shared)}",
        f"**Core contract violations:** {len(contract_vios)}",
    ]

    if raw_sharing:
        lines += ["", "#### Raw-series sharing (CORE tier)", ""]
        for item in raw_sharing:
            lines.append(f"- **{item['severity']}**: {item['raw_series']} → {item['channels']}")

    if group_sharing:
        lines += ["", "#### Independence-group crossings (CORE tier)", ""]
        for item in group_sharing:
            lines.append(f"- **{item['severity']}**: {item['independence_group']!r} → {item['channels']}")

    if authorized:
        lines += ["", "#### Authorized shared derivatives", ""]
        for item in authorized:
            lines.append(
                f"- {item['proxy']} ({item['tier']}): raw={item['raw_series']!r} "
                f"across {item['channels']}, reason={item['reason']}"
            )

    if diagnostic_shared:
        lines += ["", "#### Diagnostic shared sources", ""]
        for item in diagnostic_shared:
            lines.append(
                f"- {item['diagnostic_proxy']} ({item['diagnostic_channel']}): "
                f"raw={item['raw_series']!r} feeds {item['voting_channels']} voting"
            )

    if contract_vios:
        lines += ["", "#### Core contract violations", ""]
        for v in contract_vios:
            lines.append(
                f"- {v['proxy']} ({v['tier']}, group={v['independence_group']!r}): "
                f"{v['violation']} in {v['channel']}"
            )

    # Original governance flags
    if bundle.audit["warnings"]:
        lines += ["", "### Governance Flags", ""]
        for warning in bundle.audit["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines += ["", "No channel-collapse governance flag was triggered."]

    lines += [
        "",
        "---",
        "",
        "## 3. Per-Event Path Diagnostics",
        "",
    ]

    for r in results:
        lines.append(f"### {r.event_name} (`{r.event_id}`)")
        lines.append(
            f"**Category:** {r.category} | **Peak:** {r.peak_date} | "
            f"**Peak regime:** {r.peak_regime}"
        )
        lines.append(f"**Observed path:** {r.path_text}")
        lines.append("")
        lines.append("| Channel | First Trigger | Days Before Peak | Value At Peak | Coverage | Confidence |")
        lines.append("|---|---|---:|---:|---:|---|")
        trigger_by_channel = {item["channel"]: item for item in r.observed_path}
        for ch in CHANNELS:
            item = trigger_by_channel.get(ch, {})
            lines.append(
                f"| {ch} | {item.get('date', 'not triggered')} | "
                f"{item.get('days_before_peak', '')} | "
                f"{r.channel_at_peak.get(ch, float('nan')):.3f} | "
                f"{r.channel_coverage_at_peak.get(ch, 0.0):.2f} | "
                f"{r.channel_confidence_at_peak.get(ch, 'INVALID')} |"
            )
        if r.benchmark_context:
            lines.append("")
            lines.append("Benchmark/context max inside event window:")
            parts = [f"{k}={v:.2f}" for k, v in sorted(r.benchmark_context.items())]
            lines.append(", ".join(parts))
        lines.append("")
        for note in r.notes:
            lines.append(f"> {note}")
        lines.append("")

    lines += [
        "---",
        "",
        "## 4. Path Summary",
        "",
        "| Event | Category | Peak Regime | Observed Path | Confidence Boundary | Calm Window Note |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        conf_boundary = ", ".join(
            f"{ch}:{label}" for ch, label in r.channel_confidence_at_peak.items()
            if label != "VALID_FULL"
        ) or "all full"
        fp_note = calm_contamination.get(r.event_id, "clean")
        lines.append(
            f"| {r.event_name} | {r.category} | {r.peak_regime} | "
            f"{r.path_text} | {conf_boundary} | {fp_note} |"
        )

    # Calm contamination
    contaminated = {k: v for k, v in calm_contamination.items() if v != "clean"}
    if contaminated:
        lines += ["", "---", "", "## 5. Calm-Period Contamination", ""]
        for eid, note in contaminated.items():
            name = next((r.event_name for r in results if r.event_id == eid), eid)
            lines.append(f"- **{name}** ({eid}): {note}")

    # Governance
    lines += [
        "",
        "---",
        "",
        "## 6. Proxy Registry",
        "",
        "| Component | Channel | Role | Mechanism | Available | Raw Series |",
        "|---|---|---|---|---|---|",
    ]
    for row in bundle.registry:
        raw = ", ".join(row["raw_series"])
        lines.append(
            f"| {row['name']} | {row['channel']} | {row['role']} | "
            f"{row['mechanism']} | {row['available']} | {raw} |"
        )

    # Caveats
    lines += [
        "",
        "---",
        "",
        "## 7. Caveats",
        "",
        "1. **No scalar success target:** This replay reports paths and boundaries. It intentionally avoids strong/good/weak model evaluation.",
        "2. **HY OAS gap:** BAMLH0A0HYM2/BAMLC0A0CM/BAMLC0A4CBBB only available from 2023-05 in this cache. Pre-2023 credit-curve deformation uses BAA10YM.",
        "3. **TEDRATE retired:** TEDRATE is benchmark-only and not a current structural proxy.",
        "4. **MOVE limited:** yfinance only provides ~1 year of MOVE history.",
        "5. **X_PRE weak observability:** Public data still captures traces, not the hidden stock itself.",
        "6. **Rolling normalization:** Early events can have lower channel coverage because rolling z-scores require a warm-up window.",
        "7. **No OOS validation:** This is a historical replay, not a walk-forward backtest.",
        "8. **Data vintage:** All series use latest-vintage data, not real-time vintages available at each event date.",
        "",
        "---",
        "",
        "## Actionable Verdict",
        "- Verdict: ACTION_REQUIRED",
        "- Severity: MEDIUM",
        "- Owner: governance",
        "- Required Action: Treat proxy outputs according to attached semantic metadata and promotion routing gate.",
        "- Closure Condition: Reports pass verdict gate, proxy registry carries semantic metadata, and promotion decision is explicit.",
        "",
    ]

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main(cfg: DictConfig) -> None:
    # Resolve paths from cfg, then write config_snapshot.json BEFORE any work
    # begins. This closes the governance gap recorded for 2026-04-22_WEEKLY:
    # the snapshot now reflects the resolved config at run start, not a
    # backfill.
    output_dir = Path(cfg.output.dir)
    event_dir = output_dir / cfg.output.event_subdir
    panel_path = Path(cfg.panel.path)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)
    snapshot = OmegaConf.to_container(cfg, resolve=True)
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, default=str)
    )

    print("=" * 70)
    print("Structural Deformation System — Path Replay v0.3")
    print(f"  release={cfg.panel.release_id}  tag={cfg.run.tag}")
    print(f"  output={output_dir}")
    print("=" * 70)

    # 1. Load data
    print("\n[1/4] Loading official Harvester panel...")
    panel = load_official_panel(panel_path)
    print(f"  Panel: {panel.shape[1]} series, {len(panel)} days")
    print(f"  Range: {panel.index.min().date()} -> {panel.index.max().date()}")
    present = [c.replace('FRED:', '').replace('H41:', '').replace('TREASURY:', '').replace('YFINANCE:', '') for c in panel.columns]
    print(f"  Series: {', '.join(sorted(present))}")

    # 2. Build audited measurement layer
    print("\n[2/4] Building audited M/D/K/X_PRE/X_REALIZED measurement layer...")
    bundle = build_measurement_bundle(panel)
    channels = bundle.channels

    # v2: check hard_errors before proceeding
    hard_errors = bundle.audit.get("hard_errors", [])
    if hard_errors:
        print("\n  *** HARD_ERROR — core measurement isolation violated ***")
        for err in hard_errors:
            print(f"    {err}")
        print("  Aborting. Fix raw-series or independence_group sharing before re-running.")
        sys.exit(1)

    thresholds = calibrate_path_thresholds(channels)
    # Phase 4: realized-activation audit needs thresholds, computed after the
    # main audit pass, then merged into bundle.audit so downstream report code
    # can reference it.
    bundle.audit["realized_activation_quality"] = compute_realized_activation_quality(
        channels, bundle.components, bundle.registry, STRESS_EVENTS, thresholds
    )
    print(f"  Channels: {', '.join(CHANNELS)}")
    # Show coverage stats
    for ch in CHANNELS:
        valid = channels[ch].notna().sum()
        median_cov = bundle.coverage[ch].median()
        print(f"  {ch}: {valid}/{len(channels)} valid days, median coverage={median_cov:.2f}")
    if bundle.audit["warnings"]:
        print("  Governance flags:")
        for warning in bundle.audit["warnings"]:
            print(f"    - {warning}")
    # Cross-reference family-monoculture warnings to known data gaps so the
    # operator can immediately see which warnings require Harvester-side
    # data acquisition vs. which can be resolved at the measurement layer.
    gap_by_channel = {g["channel"]: g for g in bundle.audit.get("known_data_gaps", [])}
    monoculture_channels = []
    for w in bundle.audit.get("warnings", []):
        if w.startswith("FAMILY_MONOCULTURE"):
            for ch in CHANNELS:
                if f": {ch} " in w:
                    monoculture_channels.append(ch)
                    break
    if monoculture_channels:
        print("  Known data gaps (Harvester-side, see audit.known_data_gaps):")
        for ch in monoculture_channels:
            gap = gap_by_channel.get(ch)
            if not gap:
                continue
            print(f"    - {ch}: owner={gap['owner']}; unblock = {gap['unblock']}")
    raq = bundle.audit.get("realized_activation_quality", {})
    if raq:
        print(
            f"  X_REALIZED activation: recall={raq.get('activation_recall', 0):.2f} "
            f"({raq.get('events_activated', 0)}/{raq.get('events_with_data', 0)} events @ warning), "
            f"false_rate(critical)={raq.get('false_activation_rate_at_critical', 0):.4f} "
            f"({raq.get('calm_activated_at_critical', 0)}/{raq.get('calm_days', 0)} calm days), "
            f"false_rate(warning)={raq.get('false_activation_rate_at_warning', 0):.4f} "
            f"(includes minor events not on STRESS_EVENTS list)"
        )

    # 3. Save channel paths and benchmark controls. No scalar success target is emitted.
    print("\n[3/4] Saving channel paths + benchmark controls...")
    benchmarks = build_benchmark_signals(panel)
    all_signals = pd.concat(
        [
            channels.add_prefix("channel_"),
            bundle.coverage.add_prefix("coverage_"),
            benchmarks,
        ],
        axis=1,
    )
    all_signals.to_parquet(output_dir / "all_signals.parquet")
    bundle.components.to_parquet(output_dir / "proxy_components.parquet")
    bundle.coverage.to_parquet(output_dir / "channel_coverage.parquet")
    # Map the replay's internal channel names to the canonical Σ channel names
    # (the bundle uses "D_contraction"; the canonical Σ vector uses "D"). Only
    # channels with real data are passed; build_sigma_vector treats the rest as
    # NOT_IMPLEMENTED (absent ≠ a 0.0 vote) so the four channels stay co-equal.
    _SIGMA_CHANNEL_NAMES = {"M": "M", "D_contraction": "D", "K": "K", "X_agg": "X_agg"}
    latest_scores = {
        canonical: float(bundle.channels[internal].dropna().iloc[-1])
        for internal, canonical in _SIGMA_CHANNEL_NAMES.items()
        if internal in bundle.channels and not bundle.channels[internal].dropna().empty
    }
    latest_scores["operator_penalty"] = float(bundle.audit.get("pc1_variance_share", 0.0))
    semantic = SemanticRegistry(SEMANTIC_REGISTRY_PATH)
    sigma_vector = build_sigma_vector(latest_scores, semantic)
    sigma_output = {
        "sigma_scalar": None,
        "sigma_vector": sigma_vector,
        "interpretation_scope": "scalar summary only; structural interpretation requires sigma_vector",
    }
    (output_dir / "proxy_registry.json").write_text(json.dumps(bundle.registry, indent=2))
    (output_dir / "sigma_vector.json").write_text(json.dumps(sigma_output, indent=2))
    (output_dir / "measurement_audit.json").write_text(json.dumps(bundle.audit, indent=2, default=str))
    print(f"  Signals: {all_signals.shape[1]} columns")

    # 4. Analyze
    print("\n[4/4] Analyzing stress events...")
    results = []
    for ev in STRESS_EVENTS:
        peak = pd.Timestamp(ev["peak"])
        if peak < panel.index.min() + pd.Timedelta(days=cfg.run.pre_event_warmup_days):
            print(f"  SKIP {ev['name']}: insufficient pre-peak data")
            continue
        r = analyze_event(ev, benchmarks, bundle, thresholds)
        results.append(r)

        # Save event window data
        pre = pd.Timestamp(ev["pre_start"])
        post = pd.Timestamp(ev["post_end"])
        ev_data = all_signals[(all_signals.index >= pre) & (all_signals.index <= post)]
        ev_data.to_csv(event_dir / f"{ev['id']}_signals.csv")

        print(f"  {ev['name']}: regime={r.peak_regime}, path={r.path_text}")

    contamination = check_calm_contamination(results, STRESS_EVENTS)

    for r in results:
        if contamination.get(r.event_id, "clean") != "clean":
            r.notes.append(f"Calm window {contamination[r.event_id]}")

    report = generate_report(results, bundle, thresholds, contamination)
    report_path = output_dir / "evaluation_report.md"
    report_path.write_text(report)
    validate_report_verdict(report_path)

    # JSON results
    json_results = []
    for r in results:
        json_results.append({
            "event_id": r.event_id, "event_name": r.event_name,
            "peak_date": r.peak_date, "category": r.category,
            "peak_regime": r.peak_regime,
            "observed_path": r.observed_path,
            "path_text": r.path_text,
            "channel_at_peak": r.channel_at_peak,
            "channel_coverage_at_peak": r.channel_coverage_at_peak,
            "channel_confidence_at_peak": r.channel_confidence_at_peak,
            "benchmark_context": r.benchmark_context,
            "governance_flags": r.governance_flags,
            "notes": r.notes,
        })
    (output_dir / "results.json").write_text(json.dumps(json_results, indent=2, default=str))

    print(f"\n{'='*70}")
    print(f"Evaluation complete. {len(results)} events analyzed.")
    print("  Output mode: path diagnostics, no scalar evaluation target.")
    print(f"  Report: {output_dir / 'evaluation_report.md'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main(load_cfg())
