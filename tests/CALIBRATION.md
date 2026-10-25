# Tests and calibration

None of the checks below has been run against the voice recognition and talk-back build. Run them by hand. Before that build, the wake-word pipeline passed an offline check with synthetic voices (see the README). Each step lists what to check and the setting to tune.

Paths: `PY=~/.local/share/mantri/venv/bin/python`, `M=~/.local/share/mantri/mantri.py`.

## 1. Wake-word parsing (no audio)

```bash
$PY tests/test_wake.py        # or: $PY -m pytest tests
```

Expect: `ok, 21 cases`. Add every misheard spelling of "Mantri" from the journal to `WAKE_SPELLINGS` and add a case for it here.

## 2. Talk back

```bash
$PY $M --say "Opening Firefox. It's 3:42 PM."
```

Check the voice, speed and latency, then set `MANTRI_VOICE_SID` and `MANTRI_VOICE_SPEED` in `mantri.service`. If replies start late, note the delay. Kokoro on 4 CPU threads should take well under a second for a short reply.

## 3. Enrollment

```bash
mantri-toggle off && mantri-enroll rajeev && mantri-toggle on
```

Enrollment prints a self-match score for each phrase. Expect about 0.7 or higher. A low phrase usually means noise or clipping, so redo the enrollment in a quieter moment.

## 4. Voice recognition threshold (`MANTRI_SPEAKER_THRESHOLD`, default 0.5)

Watch `journalctl --user -u mantri -f`. Each wake logs `speaker <name> <score> ok|REJECTED`.

1. Say 10 commands yourself: quiet room, across the room, TV on, music on.
2. Have another person say 10. Also play a YouTube clip of someone saying "Mantri".
3. Set the threshold between the lowest score for your own voice and the highest score for anyone else. If those two ranges overlap, re-enroll from your usual position with the TV on.

## 5. Whole pipeline on recordings

Record real sessions (`pw-record --rate 16000 --channels 1 --format s16 out.wav`), then run:

```bash
$PY $M --file out.wav
```

This prints every utterance, its transcript, the speaker score and what would run. Use it to tune the VAD settings at the top of `mantri.py`: `VAD_START`, `VAD_END`, `END_SILENCE_SECS` and `MAX_UTTERANCE_SECS`.

## 6. Live checks

| Check | Expect |
|---|---|
| "Mantri, open firefox" | Firefox opens and Mantri says "Opening Firefox" |
| "Mantri" … chime … "what time is it" | Mantri speaks the time |
| An hour of TV and conversation with no wake word | No chime, no toast and no journal lines |
| A reply while music plays | No self-trigger, and the next command still works |
| Toggle off from the bar | The service is inactive and the mic is released (no `mantri` in `pw-top`) |
| Reboot while off | Mantri stays off |
