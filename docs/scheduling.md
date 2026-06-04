# Scheduling the readout

The `readout` stage is idempotent: it re-scores whatever is in the configured source and rewrites
`DAILY_PULSE.md`. Once logging is live and the pipeline is approved, schedule it so the
readout stays current as real data accumulates.

## cron

```bash
prd-to-readout schedule --cron "0 9 * * *"
```

prints a line to add via `crontab -e`, for example:

```
0 9 * * * cd /path/to/project && prd-to-readout readout -w /path/to/project >> /path/to/project/.pulse/readout.log 2>&1
```

## macOS launchd

Create `~/Library/LaunchAgents/com.prd-to-readout.readout.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.prd-to-readout.readout</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>prd-to-readout</string>
    <string>readout</string>
    <string>-w</string>
    <string>/path/to/project</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
```

Then `launchctl load ~/Library/LaunchAgents/com.prd-to-readout.readout.plist`.

## Repeated looks

A daily readout runs a fresh significance test each day. That is repeated-looks (peeking) and
inflates false positives. The readout's Methodology section flags this; for a formal decision,
treat a single day's significance cautiously and prefer a pre-registered horizon or a
sequential-testing method.
