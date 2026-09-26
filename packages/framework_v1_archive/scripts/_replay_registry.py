"""Replay registry — data definitions for structural replay.

Type aliases, stress events, state variables, proxy specifications,
and the canonical PROXY_REGISTRY.

This is a pure data module — no computation logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

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


def _verify_release_if_under_exports(panel_path: Path) -> None:
    """Phase 4.2: if panel_path is under Data/harvester/exports/<release>/,
    verify that release is finalized before reading. No-op for test fixtures
    or non-release paths."""
    parts = panel_path.parts
    release_root: Path | None = None
    for i, part in enumerate(parts):
        if part == "exports" and i + 1 < len(parts):
            release_root = Path(*parts[: i + 2])
            break
    if release_root is None or not release_root.exists():
        return
    try:
        from verity.runtime._release_boundary import verify_release_finalized

        verify_release_finalized(release_root)
    except ImportError:
        # _release_boundary not on path (e.g. harvester standalone test) -
        # skip the check rather than crash.
        pass


def load_official_panel(panel_path: Path) -> pd.DataFrame:
    """Load the official Harvester panel and return wide-format DataFrame.

    Built manually as per-series Series -> DataFrame to avoid a pandas/
    numpy datetime64[us] bug (seen on Python 3.14) where pivot_table /
    unstack on this parquet produces an index whose int64 timestamp
    values are silently corrupted into 1953-1957 range - causing all
    .loc[real_date] lookups to fail or return wrong rows. See
    investigation 2026-05-18 in conversation history.

    Phase 4.2: verifies the harvester release is finalized before reading,
    so an unfinalized/tampered ``latest`` cannot feed the measurement path.
    """
    _verify_release_if_under_exports(panel_path)
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
CHANNELS: list[str] = [
    "M",
    "D_contraction",
    "K",
    "X_agg",
    "X_PRE",
    "X_REALIZED",
    "Pi_t",
]

from scripts._replay_transforms import (  # noqa: E402
    _accel_abs,
    _butterfly,
    _component,
    _daily_jump_variation,
    _first_series,
    _jump_activation_score,
    _native_freq_diff_abs,
    _series,
    _spread,
    _variance_risk_premium,
    _vix_term_ratio,
)

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
    # SKEW and VVIX: options-derived tail risk measures.
    # Finance-2.tex §4.4 specifies K as "options-derived IV/jump/tail".
    # SKEW = CBOE skew index (tail risk pricing), VVIX = vol of vol.
    # Both are canonical K proxies per the theoretical specification.
    ProxySpec(
        name="K_skew_index",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("YFINANCE:^SKEW",),
        raw_family="OPTIONS_TAIL",
        independence_group="skew_surface",
        mechanism="tail_risk_pricing",
        transform="CBOE SKEW index, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(_series(p, "YFINANCE:^SKEW"), freq="daily"),
        note="CBOE SKEW index — measures tail risk pricing in S&P 500 options. "
             "Available 2010+. Canonical K proxy per Finance-2.tex §4.4.",
        canonical_status="canonical_voting",
        canonical_subbasket="K.tail_risk_skew",
        canonical_alignment_note=(
            "SKEW measures out-of-the-money put pricing relative to ATM — "
            "the canonical tail-risk/curvature signal for K. "
            "Finance-2.tex §4.4: K is options-derived."
        ),
    ),
    ProxySpec(
        name="K_vvix",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("YFINANCE:^VVIX",),
        raw_family="OPTIONS_VOL_OF_VOL",
        independence_group="vol_of_vol",
        mechanism="vol_of_vol_stress",
        transform="CBOE VVIX, daily 21d mean, daily 252d rolling z-score",
        builder=lambda p: _component(_series(p, "YFINANCE:^VVIX"), freq="daily"),
        note="CBOE VVIX — volatility of VIX (vol-of-vol). Measures second-order "
             "stress in options market. Available 2012+.",
        canonical_status="canonical_voting",
        canonical_subbasket="K.vol_of_vol",
        canonical_alignment_note=(
            "VVIX captures the rate of change of fear — when VIX itself becomes "
            "volatile, options market is under structural stress. "
            "Complementary to SKEW (tail shape) vs VVIX (fear velocity)."
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
        name="K_u2_jump_intensity_daily",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("CBOE:SPX", "SPY"),
        raw_family="REALIZED_JUMP",
        independence_group="jump_intensity",
        mechanism="bipower_variation_or_realized_jump",
        transform="daily RV − bipower variation (Barndorff-Nielsen), robust z-score",
        builder=lambda p: _component(_daily_jump_variation(p), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u2_jump_intensity",
        canonical_alignment_note=(
            "Daily-frequency jump proxy (coarser than intraday bipower, but "
            "causal and free). Replaces awaiting_data stub. §4.4 compliant."
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
        transform="(superseded by K_u2_jump_intensity_daily; kept for audit continuity)",
        builder=lambda p: None,
        canonical_status="awaiting_data",
        canonical_subbasket="K.u2_jump_intensity",
        canonical_alignment_note="Superseded by daily RV-BV proxy; intraday bipower remains optional upgrade.",
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
        name="K_vix_vix3m_ratio",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("FRED:VIXCLS", "CBOE:VIX3M"),
        raw_family="CBOE_IVTS",
        independence_group="iv_distortion",
        mechanism="near_term_vol_inversion",
        transform="VIX/VIX3M ratio (inversion >1), robust z-score",
        builder=lambda p: _component(_vix_term_ratio(p), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u1_iv_distortion",
        canonical_alignment_note=(
            "Classic near-term panic signal: term-structure inversion. "
            "Complements the butterfly twist with a slope/ratio view."
        ),
    ),
    ProxySpec(
        name="K_variance_risk_premium",
        target_variable="K",
        tier="core",
        freq="daily",
        raw_series=("FRED:VIXCLS", "CBOE:SPX", "SPY"),
        raw_family="VRP_HAR",
        independence_group="iv_distortion",
        mechanism="variance_risk_premium",
        transform="VIX^2 − causal HAR-RV forecast (Corsi), robust z-score",
        builder=lambda p: _component(_variance_risk_premium(p), freq="daily"),
        canonical_status="canonical_voting",
        canonical_subbasket="K.u1_iv_distortion",
        canonical_alignment_note=(
            "Literature-backed curvature/insurance-price measure. Positive VRP "
            "= panic pricing; compression = complacency."
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
        name="X_agg_cftc_lev_funds_net",
        target_variable="X_agg",
        tier="core",
        freq="weekly",
        raw_series=("CFTC_TFF_LEV_SP",),
        raw_family="CFTC_TFF",
        independence_group="positioning_leverage",
        mechanism="leveraged_fund_net_position_extremes",
        transform="CFTC TFF leveraged-funds net E-mini S&P position, weekly robust z-score",
        builder=lambda p: _component(
            _first_series(p, "CFTC_TFF_LEV_SP", "EXT:CFTC_TFF_LEV_SP", limit=10),
            freq="weekly",
        ),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.positioning_leverage",
        canonical_alignment_note=(
            "Batch-2 free CFTC TFF feed. Extreme leveraged-fund positioning is the "
            "X_agg 'aggregate vulnerability' observation the theory wants."
        ),
    ),
    ProxySpec(
        name="X_agg_nyfed_pd_treasury_net",
        target_variable="X_agg",
        tier="core",
        freq="weekly",
        raw_series=("NYFED_PD_TREASURY_NET",),
        raw_family="NYFED_PD",
        independence_group="dealer_balance_sheet",
        mechanism="primary_dealer_treasury_net",
        transform="NY Fed PD net Treasury positions (PDPOSGST-TOT), weekly robust z-score",
        builder=lambda p: _component(
            _first_series(p, "NYFED_PD_TREASURY_NET", "EXT:NYFED_PD_TREASURY_NET", limit=10),
            freq="weekly",
        ),
        canonical_status="canonical_voting",
        canonical_subbasket="X_agg.dealer_balance_sheet",
        canonical_alignment_note=(
            "Batch-2 NY Fed primary-dealer statistics — direct shadow-leverage "
            "observation superior to heavily-revised NFCILEVERAGE alone."
        ),
    ),
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
