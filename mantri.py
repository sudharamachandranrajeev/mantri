#!/usr/bin/env python3
"""Mantri: always-listening voice control for Omarchy.

Say "Mantri, open firefox" (or "Mantri", wait for the chime, then the command).

Pipeline, fully local:
  mic -> Silero VAD cuts speech into utterances -> Whisper transcribes each
  one -> only a sentence that begins with the wake word is run through
  `mantri-command`.

Nothing is acted on, and no chime or notification fires, unless Whisper
actually heard the wake word. The previous openWakeWord "hey jarvis" model
fired on ordinary speech and TV audio, which this design avoids.

  mantri.py                 listen on the microphone (the systemd service)
  mantri.py --file a.wav    run the pipeline over a 16 kHz mono WAV and print
                            what would happen (for testing and tuning)
"""

import argparse
import collections
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import wave

import numpy as np

# --- Settings ---------------------------------------------------------------
WAKE_WORD = "mantri"
# Whisper spellings of "Mantri" seen in testing; matched on the first words only.
WAKE_SPELLINGS = {"mantri", "mantree", "mantry", "montri", "montree", "mantrie",
                  "muntri", "mandri", "mantris"}
WAKE_PREFIXES = {"hey", "hi", "ok", "okay", "oh", "a"}  # allowed before the wake word
WHISPER_MODEL = os.environ.get("MANTRI_WHISPER_MODEL", "base.en")
VAD_START = 0.5             # speech probability that opens an utterance
VAD_END = 0.35              # ...and that counts as silence again
END_SILENCE_SECS = 0.7      # silence that ends an utterance
MIN_SPEECH_SECS = 0.25      # ignore clicks and coughs
MAX_UTTERANCE_SECS = 8.0    # hard cap, then the utterance is cut (keeps TV audio cheap)
COMMAND_WAIT_SECS = 5.0     # after a bare "Mantri", how long to wait for the command
COMMAND_HANDLER = os.path.expanduser("~/.local/bin/mantri-command")
CHIME = "/usr/share/sounds/freedesktop/stereo/message.oga"
# Always listen on the built-in mic. Recording from a Bluetooth headset forces it
# into HFP (call) mode, which breaks A2DP playback on the "Both Headphones" sink.
MIC_SOURCE = os.environ.get("MANTRI_MIC_SOURCE", "alsa_input.pci-0000_00_1f.3.analog-stereo")
# ---------------------------------------------------------------------------

RATE = 16000
FRAME = 512  # 32 ms, the Silero VAD window
FRAME_SECS = FRAME / RATE
PRE_ROLL_FRAMES = int(0.3 / FRAME_SECS)


def log(*args):
    print(*args, flush=True)


def notify(title, body="", timeout=3000):
    subprocess.Popen(
        ["notify-send", "-a", "Mantri", "-t", str(timeout),
         "-h", "string:x-canonical-private-synchronous:mantri", title, body],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def chime():
    if os.path.exists(CHIME):
        subprocess.Popen(["pw-play", CHIME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Vad:
    """Streaming wrapper around the Silero VAD v6 model bundled with faster-whisper."""

    CONTEXT = 64

    def __init__(self):
        import onnxruntime
        from faster_whisper.utils import get_assets_path

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            os.path.join(get_assets_path(), "silero_vad_v6.onnx"),
            providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)

    def __call__(self, frame):
        x = np.concatenate([self.context, frame])[None, :]
        self.context = frame[-self.CONTEXT:]
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        return float(out.reshape(-1)[0])


def utterances(frames, vad):
    """Group a stream of float32 frames into speech utterances (numpy arrays)."""
    pre_roll = collections.deque(maxlen=PRE_ROLL_FRAMES)
    current, silent, speech = None, 0.0, 0.0
    for frame in frames:
        p = vad(frame)
        if current is None:
            pre_roll.append(frame)
            if p >= VAD_START:
                current, silent, speech = list(pre_roll), 0.0, 0.0
                pre_roll.clear()
            continue
        current.append(frame)
        if p >= VAD_END:
            silent = 0.0
            speech += FRAME_SECS
        else:
            silent += FRAME_SECS
        if silent >= END_SILENCE_SECS or len(current) * FRAME_SECS >= MAX_UTTERANCE_SECS:
            if speech >= MIN_SPEECH_SECS:
                yield np.concatenate(current)
            current = None
            vad.reset()


class Transcriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=4)

    def __call__(self, audio):
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, condition_on_previous_text=False,
            without_timestamps=True, vad_filter=False,
            # Teaches Whisper the spelling; without it "Mantri" comes out as
            # Mountree, Maundry, Mentory... (see tests/README.md).
            initial_prompt="Mantri, open Firefox. Hey Mantri, volume up.")
        return " ".join(s.text.strip() for s in segments).strip()


def words(text):
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def strip_wake(w):
    """Words after a leading wake word, or None if the words don't start with one."""
    i = 0
    while i < len(w) and i < 2 and w[i] in WAKE_PREFIXES:
        i += 1
    if i < len(w) and w[i] in WAKE_SPELLINGS:
        return w[i + 1:]
    # "man tree", "mon tree"
    if i + 1 < len(w) and w[i] in {"man", "mon", "mun"} and w[i + 1] in {"tree", "tri", "three", "try"}:
        return w[i + 2:]
    return None


def split_wake(text):
    """Find the wake word at the start of a sentence and return the command
    after it: the rest of that sentence, else the next sentence ("Mantri. Open
    files."). "" means a bare wake word, None means no wake word.

    Only sentence starts count, so "the chief minister met the mantri" is
    ignored, and background speech before or after the command is dropped
    (a TV in the room keeps the VAD open, so one utterance can hold several)."""
    sentences = [words(s) for s in re.split(r"[.!?]+", text)]
    sentences = [s for s in sentences if s]
    for n, sentence in enumerate(sentences):
        rest = strip_wake(sentence)
        if rest is None:
            continue
        if not rest and n + 1 < len(sentences) and strip_wake(sentences[n + 1]) is None:
            rest = sentences[n + 1]
        return " ".join(rest)
    return None


class Assistant:
    """Turns utterances into actions. `run` is what happens to a recognised command."""

    def __init__(self, transcribe, run):
        self.transcribe = transcribe
        self.run = run
        self.awaiting_until = 0.0

    def handle(self, audio, now):
        awaiting = now < self.awaiting_until
        self.awaiting_until = 0.0
        text = self.transcribe(audio)
        command = split_wake(text)
        if awaiting and command is None:
            # The utterance after a bare "Mantri" is the command itself.
            command = " ".join(words(re.split(r"[.!?]+", text)[0]))
        if command is None:
            return  # ordinary speech: ignore silently, log nothing that was said
        log(f"Heard: {text!r}")
        if command:
            self.run(command, text)
            return
        # Bare wake word: chime and take the next utterance as the command.
        self.awaiting_until = now + COMMAND_WAIT_SECS
        chime()
        notify("🎙 Mantri", "Listening…", int(COMMAND_WAIT_SECS * 1000))


def mic_frames(stop):
    """Yield float32 frames from the mic; a reader thread keeps the pipe drained
    while Whisper is busy so audio is never dropped."""
    q = queue.Queue(maxsize=int(30 / FRAME_SECS))

    def reader():
        while not stop.is_set():
            mic = subprocess.Popen(
                ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16",
                 "--target", MIC_SOURCE, "-P", "media.name=mantri", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            try:
                buf = b""
                while not stop.is_set():
                    part = mic.stdout.read(FRAME * 2 - len(buf))
                    if not part:
                        break
                    buf += part
                    if len(buf) == FRAME * 2:
                        frame = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768
                        buf = b""
                        try:
                            q.put_nowait(frame)
                        except queue.Full:
                            pass
            finally:
                mic.terminate()
                mic.wait()
            if not stop.is_set():
                log("Mic stream ended; reopening")
                time.sleep(1)
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    while (frame := q.get()) is not None:
        yield frame


def run_command(command, heard):
    log(f"Run: {command!r}")
    subprocess.run([COMMAND_HANDLER, command])


def listen():
    stop = threading.Event()

    def on_signal(*_):
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    assistant = Assistant(Transcriber(), run_command)
    log(f"Listening for '{WAKE_WORD}' on {MIC_SOURCE} (whisper {WHISPER_MODEL})")
    for audio in utterances(mic_frames(stop), Vad()):
        assistant.handle(audio, time.monotonic())
        if stop.is_set():
            break
    log("Stopped")


def from_file(path):
    with wave.open(path) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            sys.exit(f"{path}: need 16 kHz mono 16-bit WAV")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pcm = np.concatenate([pcm, np.zeros(int(2 * RATE), dtype=np.float32)])  # flush the last utterance
    frames = (pcm[i:i + FRAME] for i in range(0, len(pcm) - FRAME + 1, FRAME))

    transcribe = Transcriber()

    def show(command, heard):
        print(f"RUN {command!r}  (heard {heard!r})", flush=True)

    def traced(audio):
        text = transcribe(audio)
        print(f"  utterance {len(audio) / RATE:.1f}s -> {text!r}", flush=True)
        return text

    assistant = Assistant(traced, show)
    t = 0.0
    for audio in utterances(frames, Vad()):
        t += len(audio) / RATE
        assistant.handle(audio, t)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="process a 16 kHz mono WAV instead of the microphone")
    args = parser.parse_args()
    sys.exit(from_file(args.file) if args.file else listen())
