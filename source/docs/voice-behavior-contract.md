# Behavior Contract

## User-Visible Goal
Voice input stays off until enabled, never types a trigger through the
keyboard listener, and failed or empty captures do not paste.

## Target
- Type: CLI probe
- Launch or access: `python voice_probe.py` from `source/`
- Allowed fixtures and credential source: none

## User Tasks
1. Run the probe and read the printed clause results.
2. Confirm every clause is `PASS`.

## Expected Observable Behavior
- Voice defaults to disabled / unavailable.
- A dictation result is inserted as literal text, even if it looks like a trigger.
- A voice-command result expands only an exact trigger and does not insert the spoken word.
- A form-field result updates the form callback and does not insert globally.
- An empty transcript does not insert.
- A second press during a session is ignored.
- Shutdown after press performs no insert.

## Anti-Cheat Probes
- Change the fake transcript and confirm the inserted/expanded value changes with it.
- A non-matching command prints `no_match` and expands nothing.

## Evidence Required
- The probe stdout, one `CLAUSE ... PASS|FAIL` line per clause, ending with `RESULT pass` or `RESULT fail`.

## Out Of Scope
- Real microphone capture, real model download, packaged installer size, Handy composition, and live WER.
