# Scheduled Batch Monitor

**Date:** 2026-06-03
**Status:** ACTIVE

---

## What It Does

Runs the full Structural Replay pipeline daily, logs runtime events, and generates alerts when something is wrong.

```
Harvester → Structural Replay → Bridge → Warnings → Runtime Event → Alert
```

## Usage

```bash
# Full run (harvester + replay + bridge + warnings)
python3 scripts/daily_run.py

# Skip harvester (use existing data)
python3 scripts/daily_run.py --skip-harvester

# Dry run (print plan, don't execute)
python3 scripts/daily_run.py --dry-run
```

## Output

| File | Content |
|------|---------|
| `<<KEEP_STATE_{name}>>_events/YYYY-MM-DD.jsonl` | Daily runtime event log |
| `Output/state/alerts/latest_alert.json` | Machine-readable alert |
| `Output/state/alerts/latest_alert.md` | Human-readable alert |

## Runtime Event Schema

```json
{
  "run_id": "daily_20260603_0556",
  "started_at": "2026-06-03T05:56:35Z",
  "finished_at": "2026-06-03T05:56:36Z",
  "duration_s": 1.3,
  "status": "success",
  "steps": [...],
  "warnings": ["QUALITY: FULL_PROXY_REDUCED"],
  "data_freshness": {"status": "fresh", "stale_hours": 0.0}
}
```

## Warning Conditions

| Condition | Severity |
|-----------|----------|
| framework_output > 24h old | MEDIUM |
| framework_output missing | HIGH |
| coverage_status != ACTIVE_FULL | HIGH |
| quality_status contains PROXY_REDUCED | MEDIUM |
| Harvester release > 2 days old | MEDIUM |
| Harvester missing | HIGH |
| Any step failed | HIGH |

## Automation with cron

```bash
# Daily at 08:30
30 8 * * * cd /Users/a1/Verity && python3 scripts/daily_run.py >> /tmp/daily_run.log 2>&1
```

## Automation with macOS launchd

```xml
<!-- ~/Library/LaunchAgents/com.system.daily-run.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.system.daily-run</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/a1/Verity/scripts/daily_run.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/a1/Verity</string>
    <key>StandardOutPath</key>
    <string>/tmp/daily_run.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/daily_run.log</string>
</dict>
</plist>
```

Load with:
```bash
launchctl load ~/Library/LaunchAgents/com.system.daily-run.plist
```

## What This Solves

| Before | After |
|--------|-------|
| Manual `./sys refresh` | Automated daily run |
| No runtime events | `<<KEEP_STATE_{name}>>_events/YYYY-MM-DD.jsonl` |
| No alerts | `Output/state/alerts/latest_alert.md` |
| No freshness check | Automatic stale detection |
| Learning Hub has no data | Runtime events provide first data |
