# Design notes

Why Mantri works the way it does. The [README](../README.md) covers install and use.

## The pipeline in detail

```
pw-record (built-in mic, 16 kHz)
  -> Silero VAD: cuts the audio into utterances
  -> Whisper base.en (faster-whisper, int8, CPU): transcribes each utterance
  -> a sentence that starts with "Mantri"
  -> voice recognition: WeSpeaker CAM++ embedding must match an enrolled voice
  -> mantri-command "<rest of sentence>"
  -> talk back: its reply is spoken with Kokoro TTS
```

- **No action without the word.** The chime, notification and command fire only when Whisper
  actually hears "Mantri" at the start of a sentence. Ordinary speech and TV audio are dropped
  and never logged.
- **Spelling prompt.** Whisper doesn't know "Mantri". Without a hint it writes *Mountree*,
  *Maundry* or *Mentory*. A short `initial_prompt` fixes the spelling, and a list of
  near-spellings (`WAKE_SPELLINGS` in `mantri.py`) catches the rest.
- **Sentence starts only.** "The chief minister met the mantri" is ignored. When a TV keeps the
  VAD open, background sentences before and after the command are dropped.
- **No dropped audio.** A reader thread drains the mic into a queue while Whisper is busy.
- **Built-in mic only.** Recording from a Bluetooth headset forces it into HFP call mode, which
  breaks A2DP playback. Override with `MANTRI_MIC_SOURCE`.

## Voice recognition

A voiceprint is the average of 8 embeddings from [WeSpeaker](https://github.com/wenet-e2e/wespeaker)
CAM++ (VoxCeleb, large-margin fine-tuned, about 0.7 % EER on VoxCeleb1-O), run through
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx). With at least one voice enrolled, a wake
sentence runs only if its speaker embedding has cosine similarity of at least
`MANTRI_SPEAKER_THRESHOLD` (default 0.5) to an enrolled voiceprint. The journal logs the best
match and score for every wake, so you can calibrate from real use.

## Why these components

| Need | Chosen | Considered |
|---|---|---|
| Runtime | sherpa-onnx (Apache-2.0): ONNX, no PyTorch, one pip package for both models | SpeechBrain and Resemblyzer need PyTorch, which adds about 2 GB |
| Speaker model | WeSpeaker CAM++ LM: 28 MB, fast. CAM++ beats ECAPA-TDNN and ResNet34 at half the parameters | ResNet293 is about 0.1 % EER better and many times slower. TitaNet-large is 96 MB |
| TTS | Kokoro-82M: best open quality at this size, Apache-2.0 code and weights | Piper is faster but sounds more robotic, and the current piper1-gpl is GPL-3.0. Kitten is smaller and lower quality |

## Why this replaced "Hey Jarvis"

The first version used openWakeWord's pretrained `hey_jarvis` model at threshold 0.5, then
recorded up to 7 s and transcribed it. Its logs from three weeks, 2026-10-04 to 2026-10-25, show
why it never worked:

| Finding | Evidence |
|---|---|
| **Every wake was false.** The model fired on ordinary speech and TV. | 21 wakes and 0 real commands. Scores ranged from 0.51 to 0.99, so no threshold would have separated real wakes from false ones. |
| **Each false wake looked like random recording.** | Each one played a chime, showed a "Listening…" toast and recorded 3.5–7 s. It then said "Didn't understand" or "Didn't hear a command". |
| **The user's own attempts were not detected.** | The transcripts include "It doesn't work. It doesn't work." |
| **Whisper hallucinated on silence.** | `base.en` turns a few seconds of room noise into "Thank you." |
| **It cost CPU around the clock.** | openWakeWord ran on every 80 ms frame: about 2 h 55 min of CPU in 37 h. |
| **It logged private speech.** | Every false trigger logged whatever was said in the room. |
| **Restarts looked like failures.** | 45 "Mic error: microphone stream ended" entries, all logged on service stop, not real mic faults. |

Mantri inverts the order. It transcribes first and wakes only on the actual word, so a false
wake now needs Whisper to hear "Mantri" at the start of a sentence.

Offline test: 16 clips from 2 voices, mixed over a recording of the real room noise. Mantri ran
all 6 commands and caught both bare wake words. It ran 0 of the 8 non-wake phrases, including
"met the mantri" and "daily mantra".
