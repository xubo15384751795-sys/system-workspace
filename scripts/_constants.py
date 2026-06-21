"""Centralized named constants — single source of truth for thresholds.

All magic numbers that appear in multiple scripts should be defined here.
Import specific constants in each script::

    from _constants import CASELAB_USABLE_THRESHOLD, TRADING_DAYS_PER_YEAR

Do NOT import the entire module with ``*`` — explicit imports make
dependencies visible and greppable.
"""
from __future__ import annotations

# ─── CaseLab match quality thresholds ───────────────────────────────
# Used by: caselab_daily_signal, build_signal_card, daily_run,
# quality_field_validator, claim_ladder_tracker, signal_consensus
CASELAB_STRONG_THRESHOLD = 0.70
CASELAB_USABLE_THRESHOLD = 0.55
CASELAB_WEAK_THRESHOLD = 0.40

# ─── Trading calendar ───────────────────────────────────────────────
# Used by: structural_replay_v2, x_measurement_gate, hmm_stability_audit,
# build_signal_card, build_data_gaps
TRADING_DAYS_PER_YEAR = 252
HALF_YEAR_TRADING_DAYS = 126
TWO_YEAR_TRADING_DAYS = 504

# ─── HMM stability audit thresholds ─────────────────────────────────
# Used by: hmm_stability_audit, build_signal_card
HMM_MIN_FEATURE_COUNT = 3
HMM_DEGENERATE_ENTROPY_THRESHOLD = 0.01
HMM_STATE_BALANCE_MAX_PROP = 0.95
HMM_MEANINGFUL_PROB_THRESHOLD = 0.01
HMM_MIN_COMPATIBLE_HISTORY_CALIBRATION = 2
HMM_MIN_COMPATIBLE_HISTORY_FULL = 10
HMM_MIN_ROLLING_REFIT = 0.7
HMM_MIN_LABEL_STABILITY = 0.6
HMM_CALIBRATION_ENTROPY_THRESHOLD = 0.1

# ─── Signal direction / size classification ──────────────────────────
# Used by: build_signal_card
SIGNAL_DIRECTION_BULLISH = 0.4
SIGNAL_DIRECTION_BEARISH = -0.4
SIGNAL_SIZE_LARGE = 1.5
SIGNAL_SIZE_MODERATE = 0.7
SIGNAL_SIZE_SMALL = 0.3

# ─── Subprocess timeout tiers (seconds) ──────────────────────────────
# Used by: daily_run, run_work_cycle, _incentive_engine, _notify,
# architecture_reality_audit, refresh_output_current, sync_caselab_index
TIMEOUT_SHORT = 10
TIMEOUT_MEDIUM = 60
TIMEOUT_STANDARD = 120
TIMEOUT_LONG = 600

# ─── M/D/K/X stress direction thresholds ────────────────────────────
# Used by: caselab_daily_signal, evaluate_proxy_lifecycle
STRESS_DIRECTION_ELEVATED = 0.3
STRESS_DIRECTION_DEPRESSED = -0.3
STRESS_DIRECTION_STRONG_BUILD = 0.5
STRESS_DIRECTION_STRONG_RELIEF = -0.5
STRESS_DIRECTION_MILD_BUILD = 0.2
STRESS_DIRECTION_MILD_RELIEF = -0.2

# ─── M/D/K/X component state boundaries ─────────────────────────────
# Used by: caselab_daily_signal
K_CURVATURE_ELEVATED = 0.6
K_CURVATURE_MODERATE = 0.3
K_CURVATURE_COMPRESSED = -0.3
K_CURVATURE_STRONG_COMPRESS = -0.5
D_DETERIORATION_THRESHOLD = -0.3
D_IMPROVEMENT_THRESHOLD = -0.5
M_MACRO_STRESS = 0.5
M_MACRO_RELIEF = -0.5
M_MACRO_SIGNIFICANT = 0.3
X_CROSS_MARKET_ELEVATED = 0.4
X_CROSS_MARKET_DECLINE = -0.3
X_CROSS_MARKET_UNWIND = -0.2
SIGMA_COMPRESSION_LOW = 0.4
SIGMA_ELEVATED = 0.6
DEFAULT_SIGMA_T = 0.5

# ─── Feedback / calibration thresholds ───────────────────────────────
# Used by: threshold_review_bridge, claim_evaluator, market_feedback
FEEDBACK_SPY_1W_DROP = -0.03
FEEDBACK_SPY_1M_DROP = -0.05
FEEDBACK_SPY_1M_GAIN = 0.03
FEEDBACK_MDD_WARNING = -0.05
FEEDBACK_MDD_SAFE = -0.02
FEEDBACK_VIX_SPIKE = 5
FEEDBACK_MISSED_RATE_HIGH = 0.4
FEEDBACK_MISSED_RATE_MEDIUM = 0.25
FEEDBACK_USEFUL_RATE_LOW = 0.6
FEEDBACK_STRESS_WINDOW_MISSED_HIGH = 0.3
