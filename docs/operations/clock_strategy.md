# Runtime clock strategy

Status: active policy, 2026-08-23

The data clock is the **XNYS exchange session clock**. A daily run is
considered eligible only after the most recent completed XNYS session close;
`system_runtime.schedule_slots.completed_session_slot_key()` uses
`exchange_calendars` and fails closed if the calendar is unavailable. Weekend,
holiday, sleep/wake, and duplicate launchd wakes therefore converge on the
same completed-session key instead of inventing a wall-clock trading date.

The launchd trigger is **07:00 machine-local time**. On this Mac the local zone
is Asia/Singapore, which has no daylight-saving transition. In U.S. winter,
XNYS regular close is 16:00 America/New_York = 21:00 UTC and 07:00 Singapore
is 23:00 UTC, leaving a two-hour buffer. In U.S. summer the close is 20:00 UTC,
leaving three hours. XNYS early-close holidays leave more time. The 07:00
trigger therefore remains after the prior U.S. session close in both DST
regimes; changing the machine timezone or launch hour requires rechecking this
calculation.

The **run and evidence clock is UTC**:

- `Output/runs/daily_pipeline_YYYYMMDD_HHMMSS_*` IDs are generated from UTC.
- `release_id`, `schedule_run_id`, JSON timestamps, and daily runtime event dates
  use UTC.
- The daily scheduled wrapper exports `TZ=UTC`; the daily logger uses a UTC
  converter and emits a trailing `Z` on log timestamps.
- `StartCalendarInterval` remains local by design; it is a trigger, not an
  evidence timestamp.

The active configuration root is `configs/`. `Config/` is no longer an active
configuration authority. Its old source-registry path remains only as a
one-window compatibility bridge and emits a deprecation warning when read.
