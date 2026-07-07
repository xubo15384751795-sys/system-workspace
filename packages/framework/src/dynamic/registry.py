"""Registry of TemporalFrame definitions by case_id (diagnostic layer; not core scoring)."""

from __future__ import annotations

from src.dynamic.models import EventPhase, TemporalFrame

_FRAMES: dict[str, TemporalFrame] = {
    "ldi_2022": TemporalFrame(
        case_id="ldi_2022",
        phases=(
            EventPhase(
                name="pre_shock",
                start="2022-09-01",
                end="2022-09-22",
                dominant_mechanism="leverage / duration risk accumulation",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="2022-09-23",
                end="2022-09-27",
                dominant_mechanism="long-end gilt shock and collateral pressure",
                expected_resolution=None,
            ),
            EventPhase(
                name="intervention",
                start="2022-09-28",
                end="2022-10-14",
                dominant_mechanism="BoE emergency gilt purchase as path rewrite",
                expected_resolution=None,
            ),
            EventPhase(
                name="post_shock",
                start="2022-10-15",
                end="2022-11-15",
                dominant_mechanism="temporary stabilization and repricing",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=3,
    ),
    "svb_2023": TemporalFrame(
        case_id="svb_2023",
        phases=(
            EventPhase(
                name="pre_shock",
                start="2023-01-01",
                end="2023-03-09",
                dominant_mechanism="rate pressure and HTM / AOCI tension building",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="2023-03-10",
                end="2023-03-12",
                dominant_mechanism="deposit run and liquidity seizure",
                expected_resolution=None,
            ),
            EventPhase(
                name="intervention",
                start="2023-03-13",
                end="2023-03-17",
                dominant_mechanism="FDIC resolution and BTFP-style backstop wiring",
                expected_resolution=None,
            ),
            EventPhase(
                name="post_shock",
                start="2023-03-18",
                end="2023-04-30",
                dominant_mechanism="regional bank repricing and deposit reallocation",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=2,
    ),
    "ltcm_1998": TemporalFrame(
        case_id="ltcm_1998",
        phases=(
            EventPhase(
                name="buildup",
                start="1998-01-01",
                end="1998-08-16",
                dominant_mechanism="leveraged convergence and spread compression",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="1998-08-17",
                end="1998-09-09",
                dominant_mechanism="Russia default shock and spread dislocation",
                expected_resolution=None,
            ),
            EventPhase(
                name="spiral",
                start="1998-09-10",
                end="1998-09-22",
                dominant_mechanism="financing withdraws and liquidity spiral",
                expected_resolution=None,
            ),
            EventPhase(
                name="rescue",
                start="1998-09-23",
                end="1998-09-28",
                dominant_mechanism="Fed-sponsored consortium rescue and portfolio unwind",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=3,
    ),
    "archegos_2021": TemporalFrame(
        case_id="archegos_2021",
        phases=(
            EventPhase(
                name="pre_shock",
                start="2021-01-01",
                end="2021-03-21",
                dominant_mechanism="concentrated swap / CFD exposure accumulation",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="2021-03-22",
                end="2021-03-28",
                dominant_mechanism="margin calls and disorderly block unwind",
                expected_resolution=None,
            ),
            EventPhase(
                name="intervention",
                start="2021-03-29",
                end="2021-04-04",
                dominant_mechanism="counterparty auction / risk transfer",
                expected_resolution=None,
            ),
            EventPhase(
                name="post_shock",
                start="2021-04-05",
                end="2021-06-30",
                dominant_mechanism="prime brokerage repricing and exposure limits",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=2,
    ),
    "chf_peg_2015": TemporalFrame(
        case_id="chf_peg_2015",
        phases=(
            EventPhase(
                name="pre_shock",
                start="2014-06-01",
                end="2015-01-14",
                dominant_mechanism="EURCHF peg defense and reserve / rate pressure",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="2015-01-15",
                end="2015-01-15",
                dominant_mechanism="SNB peg discontinuity",
                expected_resolution=None,
            ),
            EventPhase(
                name="intervention",
                start="2015-01-16",
                end="2015-01-31",
                dominant_mechanism="FX volatility management and broker risk controls",
                expected_resolution=None,
            ),
            EventPhase(
                name="post_shock",
                start="2015-02-01",
                end="2015-06-30",
                dominant_mechanism="macro hedge fund and risk-parity repricing",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=1,
    ),
    "repo_spike_2019": TemporalFrame(
        case_id="repo_spike_2019",
        phases=(
            EventPhase(
                name="pre_shock",
                start="2019-08-01",
                end="2019-09-16",
                dominant_mechanism="reserve scarcity and secured funding tightness building",
                expected_resolution=None,
            ),
            EventPhase(
                name="shock",
                start="2019-09-17",
                end="2019-09-19",
                dominant_mechanism="GC repo rate spike",
                expected_resolution=None,
            ),
            EventPhase(
                name="intervention",
                start="2019-09-20",
                end="2019-10-10",
                dominant_mechanism="Fed repo operations and balance-sheet relief",
                expected_resolution=None,
            ),
            EventPhase(
                name="post_shock",
                start="2019-10-11",
                end="2019-12-31",
                dominant_mechanism="money-market normalization and year-end plumbing watch",
                expected_resolution=None,
            ),
        ),
        event_speed="acute",
        required_resolution="daily",
        observation_lag_tolerance_days=2,
    ),
}


def list_temporal_frames() -> list[str]:
    """Return sorted case_ids that have a registered TemporalFrame."""
    return sorted(_FRAMES.keys())


def get_temporal_frame(case_id: str) -> TemporalFrame:
    """Return the TemporalFrame for case_id, or raise KeyError with a clear message."""
    try:
        return _FRAMES[case_id]
    except KeyError as e:
        known = ", ".join(repr(k) for k in list_temporal_frames()) or "(none)"
        raise KeyError(f"Unknown temporal case_id {case_id!r}. Known ids: {known}") from e
