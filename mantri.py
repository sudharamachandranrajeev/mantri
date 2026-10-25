#!/usr/bin/env python3
"""Mantri: always-listening voice control for Omarchy.

Say "Mantri, open firefox" (or "Mantri", wait for the chime, then the command).

Pipeline, fully local:
  mic -> Silero VAD cuts speech into utterances -> Whisper transcribes each
  one -> only a sentence that begins with the wake word goes on -> if voices
  are enrolled, the speaker must match one -> `mantri-command` runs it ->
  its reply is spoken with Kokoro TTS.

Nothing is acted on, and no chime or notification fires, unless Whisper
actually heard the wake word. The previous openWakeWord "hey jarvis" model
fired on ordinary speech and TV audio, which this design avoids.

  mantri.py                 listen on the microphone (the systemd service)
  mantri.py --enroll NAME   record NAME's voice so Mantri obeys only enrolled voices
  mantri.py --file a.wav    run the pipeline over a 16 kHz mono WAV and print
                            what would happen, with speaker scores (calibration)
  mantri.py --say "text"    speak text with the talk-back voice
"""

import argparse
import collections
import glob
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
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
# Voice recognition: cosine similarity to an enrolled voiceprint needed to obey.
# Uncalibrated default; check the "speaker" scores in the journal and tune.
SPEAKER_THRESHOLD = float(os.environ.get("MANTRI_SPEAKER_THRESHOLD", "0.5"))
# Talk back: Kokoro voice id (21 = bf_emma, British female; 26 = bm_george) and speed.
TALKBACK = os.environ.get("MANTRI_TALKBACK", "1") != "0"
VOICE_SID = int(os.environ.get("MANTRI_VOICE_SID", "21"))
VOICE_SPEED = float(os.environ.get("MANTRI_VOICE_SPEED", "1.1"))
COMMAND_HANDLER = os.path.expanduser("~/.local/bin/mantri-command")
CHIME = "/usr/share/sounds/freedesktop/stereo/message.oga"
# Always listen on the built-in mic. Recording from a Bluetooth headset forces it
# into HFP (call) mode, which breaks A2DP playback on the "Both Headphones" sink.
MIC_SOURCE = os.environ.get("MANTRI_MIC_SOURCE", "alsa_input.pci-0000_00_1f.3.analog-stereo")
DATA = os.path.expanduser("~/.local/share/mantri")
MODELS = os.path.join(DATA, "models")
VOICES = os.path.join(DATA, "voices")  # enrolled voiceprints, one NAME.npy each
SPEAKER_MODEL = os.path.join(MODELS, "wespeaker_en_voxceleb_CAM++_LM.onnx")
KOKORO = os.path.join(MODELS, "kokoro-int8-multi-lang-v1_0")
# ---------------------------------------------------------------------------

RATE = 16000
FRAME = 512  # 32 ms, the Silero VAD window
FRAME_SECS = FRAME / RATE
PRE_ROLL_FRAMES = int(0.3 / FRAME_SECS)

ENROLL_PHRASES = [
    "Mantri, open Firefox.",
    "Mantri, what time is it?",
    "Hey Mantri, volume up.",
    "Mantri, next song.",
    "Mantri, search for the weather in Belfast.",
    "Mantri, move this window to workspace three.",
    "Mantri, take a screenshot.",
    "Mantri, lock the screen.",
]


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


class Segmenter:
    """Groups float32 frames into speech utterances; feed() returns one when it ends."""

    def __init__(self):
        self.vad = Vad()
        self.reset()

    def reset(self):
        self.vad.reset()
        self.pre_roll = collections.deque(maxlen=PRE_ROLL_FRAMES)
        self.current, self.silent, self.speech = None, 0.0, 0.0

    def feed(self, frame):
        p = self.vad(frame)
        if self.current is None:
            self.pre_roll.append(frame)
            if p >= VAD_START:
                self.current, self.silent, self.speech = list(self.pre_roll), 0.0, 0.0
                self.pre_roll.clear()
            return None
        self.current.append(frame)
        if p >= VAD_END:
            self.silent = 0.0
            self.speech += FRAME_SECS
        else:
            self.silent += FRAME_SECS
        if self.silent >= END_SILENCE_SECS or len(self.current) * FRAME_SECS >= MAX_UTTERANCE_SECS:
            audio = np.concatenate(self.current) if self.speech >= MIN_SPEECH_SECS else None
            self.reset()
            return audio
        return None


class Transcriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=4)

    def __call__(self, audio):
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, condition_on_previous_text=False,
            without_timestamps=True, vad_filter=False,
            # Teaches Whisper the spelling; without it "Mantri" comes out as
            # Mountree, Maundry, Mentory... (see README).
            initial_prompt="Mantri, open Firefox. Hey Mantri, volume up.")
        return " ".join(s.text.strip() for s in segments).strip()


class Speakers:
    """Voice recognition: compares an utterance with the enrolled voiceprints
    (WeSpeaker CAM++ speaker embeddings, cosine similarity)."""

    def __init__(self):
        import sherpa_onnx
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=SPEAKER_MODEL, num_threads=2))
        self.voices = {}
        for path in sorted(glob.glob(os.path.join(VOICES, "*.npy"))):
            self.voices[os.path.basename(path)[:-4]] = np.load(path)

    def embed(self, audio):
        stream = self.extractor.create_stream()
        stream.accept_waveform(RATE, audio)
        stream.input_finished()
        e = np.array(self.extractor.compute(stream), dtype=np.float32)
        return e / (np.linalg.norm(e) or 1.0)

    def identify(self, audio):
        """Best (name, score) among enrolled voices, or (None, 0.0) if none enrolled."""
        if not self.voices:
            return None, 0.0
        e = self.embed(audio)
        return max(((name, float(e @ v)) for name, v in self.voices.items()), key=lambda x: x[1])


class Voice:
    """Talk back with Kokoro TTS (sherpa-onnx), played on the default output."""

    def __init__(self):
        import sherpa_onnx
        k = KOKORO
        self.tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=f"{k}/model.int8.onnx", voices=f"{k}/voices.bin", tokens=f"{k}/tokens.txt",
                    lexicon=f"{k}/lexicon-gb-en.txt", data_dir=f"{k}/espeak-ng-data",
                    dict_dir=f"{k}/dict", lang="en-gb"),
                num_threads=4)))

    def say(self, text):
        audio = self.tts.generate(text, sid=VOICE_SID, speed=VOICE_SPEED)
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            with wave.open(f.name, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(audio.sample_rate)
                pcm = np.clip(np.asarray(audio.samples), -1, 1)
                w.writeframes((pcm * 32767).astype(np.int16).tobytes())
            subprocess.run(["pw-play", "-P", "media.name=mantri", f.name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def run_command(command):
    """Run mantri-command; lines it prints as "SPEAK: ..." are the reply to say."""
    log(f"Run: {command!r}")
    out = subprocess.run([COMMAND_HANDLER, command], capture_output=True, text=True).stdout
    return " ".join(l[6:].strip() for l in out.splitlines() if l.startswith("SPEAK:"))


class Assistant:
    """Turns utterances into actions.

    `run(command) -> reply` executes a recognised command, `speak(text)` talks
    back, and `speakers` (optional) gates commands on an enrolled voice."""

    def __init__(self, transcribe, run, speak=None, speakers=None):
        self.transcribe = transcribe
        self.run = run
        self.speak = speak
        self.speakers = speakers
        self.awaiting_until = 0.0
        self.awaiting_name = None

    def handle(self, audio, now):
        """Process one utterance. Returns True if Mantri made a sound."""
        awaiting = now < self.awaiting_until
        self.awaiting_until = 0.0
        text = self.transcribe(audio)
        command = split_wake(text)
        if awaiting and command is None:
            # The utterance after a bare "Mantri" is the command itself.
            command = " ".join(words(re.split(r"[.!?]+", text)[0]))
        if command is None:
            return False  # ordinary speech: ignore silently, log nothing that was said

        name = self.awaiting_name if awaiting else None
        if self.speakers and self.speakers.voices and name is None:
            name, score = self.speakers.identify(audio)
            ok = score >= SPEAKER_THRESHOLD
            log(f"Heard: {text!r}  speaker {name} {score:.2f} {'ok' if ok else 'REJECTED'}")
            if not ok:
                return False  # someone else, or the TV, said "Mantri"
        else:
            log(f"Heard: {text!r}")

        if command:
            reply = self.run(command)
            if reply and self.speak:
                self.speak(reply)
                return True
            return False
        # Bare wake word: chime and take the next utterance as the command.
        self.awaiting_until = now + COMMAND_WAIT_SECS
        self.awaiting_name = name
        chime()
        notify("🎙 Mantri", "Listening…", int(COMMAND_WAIT_SECS * 1000))
        return True


class Mic:
    """Float32 frames from pw-record. A reader thread keeps the pipe drained
    while Whisper is busy so audio is never dropped."""

    def __init__(self, stop):
        self.stop = stop
        self.q = queue.Queue(maxsize=int(30 / FRAME_SECS))
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while not self.stop.is_set():
            mic = subprocess.Popen(
                ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16",
                 "--target", MIC_SOURCE, "-P", "media.name=mantri", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            try:
                buf = b""
                while not self.stop.is_set():
                    part = mic.stdout.read(FRAME * 2 - len(buf))
                    if not part:
                        break
                    buf += part
                    if len(buf) == FRAME * 2:
                        frame = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768
                        buf = b""
                        try:
                            self.q.put_nowait(frame)
                        except queue.Full:
                            pass
            finally:
                mic.terminate()
                mic.wait()
            if not self.stop.is_set():
                log("Mic stream ended; reopening")
                time.sleep(1)
        self.q.put(None)

    def flush(self):
        """Drop audio captured so far (e.g. Mantri's own voice or chime)."""
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def __iter__(self):
        while (frame := self.q.get()) is not None:
            yield frame


def load_voice():
    if not TALKBACK:
        return None
    try:
        return Voice()
    except Exception as e:  # missing model: keep working, just silently
        log(f"Talk back off: {e}")
        return None


def load_speakers():
    try:
        speakers = Speakers()
    except Exception as e:
        log(f"Voice recognition off: {e}")
        return None
    if speakers.voices:
        log(f"Voice recognition on: {', '.join(speakers.voices)} (threshold {SPEAKER_THRESHOLD})")
    else:
        log("Voice recognition off: no voices enrolled (mantri-enroll NAME)")
    return speakers


def listen():
    stop = threading.Event()

    def on_signal(*_):
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    voice = load_voice()
    assistant = Assistant(Transcriber(), run_command, voice.say if voice else None, load_speakers())
    mic, segmenter = Mic(stop), Segmenter()
    log(f"Listening for '{WAKE_WORD}' on {MIC_SOURCE} (whisper {WHISPER_MODEL})")
    for frame in mic:
        audio = segmenter.feed(frame)
        if audio is not None and assistant.handle(audio, time.monotonic()):
            time.sleep(0.3)  # let the chime or reply tail off before listening again
            mic.flush()
            segmenter.reset()
        if stop.is_set():
            break
    log("Stopped")


def enroll(name):
    """Record the user saying a few commands and save their averaged voiceprint."""
    if subprocess.run(["systemctl", "--user", "is-active", "--quiet", "mantri"]).returncode == 0:
        sys.exit("Turn Mantri off first (mantri-toggle off) so it doesn't act on these phrases.")
    speakers = Speakers()
    stop = threading.Event()
    mic, segmenter = Mic(stop), Segmenter()
    print(f"Enrolling '{name}'. Speak normally from where you usually sit.\n")
    embeddings = []
    for n, phrase in enumerate(ENROLL_PHRASES, 1):
        input(f"[{n}/{len(ENROLL_PHRASES)}] Press Enter, then say:  {phrase}")
        mic.flush()
        segmenter.reset()
        deadline = time.monotonic() + 10
        audio = None
        for frame in mic:
            audio = segmenter.feed(frame)
            if audio is not None or time.monotonic() > deadline:
                break
        if audio is None:
            print("   didn't hear anything, skipping")
            continue
        embeddings.append(speakers.embed(audio))
        print(f"   got {len(audio) / RATE:.1f}s")
    stop.set()
    if len(embeddings) < 3:
        sys.exit("Too few phrases recorded; nothing saved.")
    voiceprint = np.mean(embeddings, axis=0)
    voiceprint /= np.linalg.norm(voiceprint)
    os.makedirs(VOICES, exist_ok=True)
    np.save(os.path.join(VOICES, f"{name}.npy"), voiceprint)
    print(f"\nSaved {len(embeddings)} samples to {VOICES}/{name}.npy")
    print("Self-match per phrase (calibration):", " ".join(f"{float(e @ voiceprint):.2f}" for e in embeddings))
    print("Turn Mantri back on with: mantri-toggle on")


def from_file(path):
    with wave.open(path) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            sys.exit(f"{path}: need 16 kHz mono 16-bit WAV")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pcm = np.concatenate([pcm, np.zeros(int(2 * RATE), dtype=np.float32)])  # flush the last utterance

    transcribe = Transcriber()

    def traced(audio):
        text = transcribe(audio)
        print(f"  utterance {len(audio) / RATE:.1f}s -> {text!r}", flush=True)
        return text

    def show(command):
        print(f"RUN {command!r}", flush=True)
        return ""

    assistant = Assistant(traced, show, speakers=load_speakers())
    segmenter, t = Segmenter(), 0.0
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        t += FRAME_SECS
        audio = segmenter.feed(pcm[i:i + FRAME])
        if audio is not None:
            assistant.handle(audio, t)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file", help="process a 16 kHz mono WAV instead of the microphone")
    group.add_argument("--enroll", metavar="NAME", help="record and save NAME's voiceprint")
    group.add_argument("--say", metavar="TEXT", help="speak TEXT with the talk-back voice")
    args = parser.parse_args()
    if args.file:
        sys.exit(from_file(args.file))
    if args.enroll:
        sys.exit(enroll(re.sub(r"[^A-Za-z0-9_-]", "", args.enroll) or "me"))
    if args.say:
        sys.exit(Voice().say(args.say))
    sys.exit(listen())
