# Mantri

Always-listening, fully local voice control for [Omarchy](https://omarchy.org/) (Hyprland on Arch).

*Mantri* (मन्त्री) is Sanskrit for a king's counsellor, the role JARVIS plays for Tony Stark.

```
"Mantri, open firefox"        "Hey Mantri, volume up"
"Mantri, workspace three"     "Mantri" … chime … "next song"
```

## How it works

```
pw-record (built-in mic, 16 kHz)
  -> Silero VAD: cuts the audio into utterances
  -> Whisper base.en (faster-whisper, int8, CPU): transcribes each utterance
  -> a sentence that starts with "Mantri" -> mantri-command "<rest of sentence>"
```

- **No action without the word.** The chime, notification and command fire only when Whisper actually hears "Mantri" at the start of a sentence. Ordinary speech and TV audio are dropped and never logged.
- **Spelling prompt.** Whisper doesn't know "Mantri". Without a hint it writes *Mountree*, *Maundry* or *Mentory*. A short `initial_prompt` fixes the spelling, and a list of near-spellings catches the rest.
- **Sentence starts only.** "The chief minister met the mantri" is ignored. When a TV keeps the VAD open, background sentences before and after the command are dropped.
- **No dropped audio.** A reader thread drains the mic into a queue while Whisper is busy.
- **Built-in mic only.** Recording from a Bluetooth headset forces it into HFP call mode, which breaks A2DP playback. Override with `MANTRI_MIC_SOURCE`.

## Commands

The phrases live in `mantri-command`, a bash `case` statement. Extend them there.

| Area | Phrases |
|---|---|
| Apps | open/launch/start *app name*, open browser/terminal/files/spotify |
| Windows | close window, fullscreen, float, workspace N, move to workspace N, next/previous workspace |
| Media | volume up/down, mute, play/pause, next/previous song |
| System | brightness up/down, lock, screenshot |
| Power (confirms first) | shut down, reboot, suspend, log out |
| Web | search for …, google …, look up … |
| Help | help, what can you do |

## Install

```bash
./install.sh
```

The script installs a venv with faster-whisper in `~/.local/share/mantri`, the `mantri-command` and `mantri-toggle` scripts in `~/.local/bin`, and the `mantri.service` systemd user unit, and the `rajeevrama.mantri` bar toggle. It downloads the Whisper base.en model (about 140 MB). If the old Hey Jarvis `voice-control` setup is present, the script removes it and points the Super+Ctrl+J binding at `mantri-toggle`.

- **Turn on or off:** use the microphone icon in the bar, Super+Ctrl+J, `mantri-toggle [on|off]` or `omarchy-shell rajeevrama.mantri toggle`. Off releases the microphone and stays off after a reboot. Rerunning `install.sh` keeps it off.
- **Logs:** `journalctl --user -u mantri -f`. Only wake-word utterances and the commands run are logged.

## Testing

```bash
python tests/test_wake.py                                   # wake-word parsing
~/.local/share/mantri/venv/bin/python mantri.py --file a.wav  # whole pipeline over a 16 kHz mono WAV
```

`--file` prints every utterance, what Whisper heard and what would have run. It is the tool for tuning thresholds against real recordings.

## Why this replaced "Hey Jarvis"

The first version used openWakeWord's pretrained `hey_jarvis` model at threshold 0.5, then recorded up to 7 s and transcribed it. Its logs from three weeks, 2026-10-04 to 2026-10-25, show why it never worked:

| Finding | Evidence |
|---|---|
| **Every wake was false.** The model fired on ordinary speech and TV. | 21 wakes and 0 real commands. Scores ranged from 0.51 to 0.99, so no threshold would have separated real wakes from false ones. |
| **Each false wake looked like random recording.** | Each one played a chime, showed a "Listening…" toast and recorded 3.5–7 s. It then said "Didn't understand" or "Didn't hear a command". |
| **The user's own attempts were not detected.** | The transcripts include "It doesn't work. It doesn't work." |
| **Whisper hallucinated on silence.** | `base.en` turns a few seconds of room noise into "Thank you." |
| **It cost CPU around the clock.** | openWakeWord ran on every 80 ms frame: about 2 h 55 min of CPU in 37 h. |
| **It logged private speech.** | Every false trigger logged whatever was said in the room. |
| **Restarts looked like failures.** | 45 "Mic error: microphone stream ended" entries, all logged on service stop, not real mic faults. |

Mantri inverts the order. It transcribes first and wakes only on the actual word, so a false wake now needs Whisper to hear "Mantri" at the start of a sentence.

Offline test: 16 clips from 2 voices, mixed over a recording of the real room noise. Mantri ran all 6 commands and caught both bare wake words. It ran 0 of the 8 non-wake phrases, including "met the mantri" and "daily mantra".

## Known limits

- Voices and TV can make the VAD merge speech into one utterance. Utterances are capped at 8 s, so a wake word spoken across that boundary can be missed. Say it again.
- Whisper `base.en` is English-only. Malayalam or Hindi speech that contains *mantri* (मुख्यमन्त्री, "chief minister") could rarely transcribe as a sentence starting with "Mantri". At worst you get a "Didn't understand" toast, because only known phrases run.
- Each utterance costs about 0.5 s of CPU on 4 threads. Constant TV audio costs about 10–15 % of one core. Silence costs only the VAD.

## License

MIT
