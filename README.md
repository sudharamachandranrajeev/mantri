<h1 align="center">
  <br>
  Mantri
  <br>
</h1>

<h4 align="center">Talk to your Omarchy computer. Say "Mantri, open Firefox" and it does, all on your own machine.</h4>

<p align="center">
  <img src="https://img.shields.io/badge/works%20on-Omarchy%20(Arch%20%2B%20Hyprland)-555" alt="Works on Omarchy (Arch + Hyprland)">
  <img src="https://img.shields.io/badge/runs-fully%20offline-2e7d32" alt="Runs fully offline">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-2b22c9" alt="MIT licence"></a>
</p>

<p align="center">
  <a href="#-what-it-does">What it does</a> •
  <a href="#-install">Install</a> •
  <a href="#-how-it-works">How it works</a> •
  <a href="#-faq-and-troubleshooting">FAQ</a> •
  <a href="#%EF%B8%8F-for-developers">For developers</a>
</p>

<table align="center">
  <tr><td><b>You say</b></td><td><b>Mantri does</b></td></tr>
  <tr><td>"Mantri, open Firefox"</td><td>Opens Firefox and says "Opening Firefox"</td></tr>
  <tr><td>"Hey Mantri, volume up"</td><td>Turns the volume up</td></tr>
  <tr><td>"Mantri, workspace three"</td><td>Jumps to workspace 3</td></tr>
  <tr><td>"Mantri" … <i>chime</i> … "what time is it"</td><td>Says "It's 3:42 PM"</td></tr>
</table>

Mantri is an always-listening voice assistant for [Omarchy](https://omarchy.org/), the Arch
Linux setup built on Hyprland. Speech recognition runs on your own computer, so nothing you say
goes online. It acts only on sentences that start with the word "Mantri". Status: **early**. It
works day to day, but it understands English only and a set list of phrases.

*Mantri* (मन्त्री) is Sanskrit for a king's counsellor, the role JARVIS plays for Tony Stark.

## ✨ What it does

- 🎙️ **Wakes on its name only** – it acts only when a sentence starts with "Mantri". TV and
  chatter are ignored and never logged.
- 🗂️ **Opens apps and moves windows** – open any installed app, close or fullscreen a window,
  and switch workspaces.
- 🎵 **Controls media and the system** – volume, play and pause, next song, brightness, lock and
  screenshot.
- 🗣️ **Talks back** – replies out loud in a natural voice, such as "Battery is at 81 percent".
- 🧑 **Knows your voice** (optional) – teach it your voice and it ignores everyone else.
- 🛑 **Asks before power actions** – shut down, reboot, suspend and log out always ask "Yes or
  No" first.
- 🔇 **Easy to switch off** – one click on the bar button stops it and frees the microphone.
- 🔒 **Fully offline** – speech-to-text, voice matching and speech all run on your CPU.

### 🗣️ Things you can say

Start each one with "Mantri". The phrases live in `mantri-command`, so you can add your own.

| Area | Say |
|---|---|
| Apps | open *app name*, open browser, open terminal, open files, open Spotify |
| Windows | close window, fullscreen, float, workspace *N*, move to workspace *N*, next / previous workspace |
| Media | volume up / down, mute, play / pause, next / previous song |
| System | brightness up / down, lock, screenshot |
| Power (asks first) | shut down, reboot, suspend, log out |
| Web | search for …, google …, look up … |
| Questions | what time is it, what's the date, battery, are you there |
| Help | help, what can you do |

## 🚀 Install

There is no download. You install it from this folder with one script.

### Step 1 – Check what you need

- **Omarchy** with its bar, on a laptop or desktop with a built-in microphone.
- **About 300 MB of free space** for the speech models.
- **An internet connection for the install only.** After that, Mantri runs offline.

### Step 2 – Install

1. Open a terminal and get the code:
   ```bash
   git clone https://github.com/sudharamachandranrajeev/mantri
   cd mantri
   ```
2. Run the installer as your normal user (not `sudo`):
   ```bash
   ./install.sh
   ```
3. Wait while it downloads the speech models. This takes a few minutes the first time.
4. When it prints **"Mantri is listening"**, it is running. A microphone button also appears in
   the bar.

The script installs everything for your user only. It adds a background service that starts at
login. Rerun it at any time to update; it keeps your on/off choice.

### Step 3 – Try it

1. Say **"Mantri, what time is it"** in a normal voice.
2. Mantri answers out loud.
3. Or say **"Mantri"** on its own, wait for the chime and the **"Listening…"** pop-up, then say
   the command within 5 seconds.
4. Say **"Mantri, help"** to see a list of commands on screen.

### Step 4 (optional) – Teach it your voice

Without this step, anyone in the room can give commands. Teach it each person once:

1. Turn Mantri off, so it does not act on the practice phrases: `mantri-toggle off`
2. Run `mantri-enroll alex` (use any name).
3. Press **Enter** before each of the 8 phrases it shows, then say the phrase.
4. Turn Mantri back on: `mantri-toggle on`

To forget a voice, delete `~/.local/share/mantri/voices/NAME.npy` and run
`systemctl --user restart mantri`.

> [!NOTE]
> Voice matching raises the bar, but it is not a lock. A recording of your voice can pass it.
> That is why power commands still ask first.

### Turn it on or off

- Click the **microphone button** in the bar, or run `mantri-toggle` (`on` or `off` to choose).
- Off stops listening, frees the microphone and stays off after a restart.

## 🧭 How it works

```mermaid
flowchart LR
    M["🎙️ Your microphone"] --> S["✂️ Splits speech<br/>into sentences"]
    S --> W["📝 Turns speech<br/>into text"]
    W -->|"starts with 'Mantri'?"| V["🧑 Checks the voice<br/>(if taught)"]
    V --> C["⚙️ Runs the command"]
    C --> T["🔊 Says the reply"]
```

- **It writes down first, then decides.** Every sentence becomes text on your computer
  (with Whisper). Only a sentence that *starts* with "Mantri" goes further. "The minister met
  the mantri" is ignored.
- **No chime, no pop-up and no log** unless it heard its name. That stops false wake-ups.
- **The voice check** compares your sentence with the voices you taught it.
- **It does not hear itself.** Sound picked up while Mantri speaks is thrown away.

The full design, and why it replaced an older "Hey Jarvis" setup, is in
[docs/design.md](docs/design.md).

### Limits

- **English only.** A Hindi or Malayalam sentence with *mantri* in it may very rarely trigger
  it. At worst you see "Didn't understand", because only known phrases run.
- **Loud TV can get in the way.** Long speech is cut at 8 seconds, so a wake word on the cut can
  be missed. Say it again. A TV talking over you also lowers the voice-match score.
- **CPU use.** About half a second of CPU per sentence. Constant TV costs about 10–15 % of one
  core. Silence costs almost nothing.

## 🔒 Your data

- **Nothing leaves the computer.** Speech-to-text, voice matching and the spoken replies all run
  locally. The only downloads are the models, during install.
- **The log** (`journalctl --user -u mantri`) holds only sentences that started with "Mantri",
  the commands run and voice-match scores. Other speech is never written down.
- **Voiceprints** are small number files in `~/.local/share/mantri/voices/`, one per person. They
  are not recordings.
- **Web searches** open your browser on Google, like typing the search yourself.

## ❓ FAQ and troubleshooting

<details>
<summary><b>It never reacts when I speak</b></summary>

1. Check that it is on: the bar button, or `systemctl --user status mantri`.
2. Watch the log while you speak: `journalctl --user -u mantri -f`.
3. Mantri listens on one fixed microphone name, a common laptop built-in mic
   (`alsa_input.pci-0000_00_1f.3.analog-stereo`). If yours has a different name, list the names
   with `pactl list short sources`. Then set `MANTRI_MIC_SOURCE` in
   `~/.config/systemd/user/mantri.service` and run
   `systemctl --user daemon-reload && systemctl --user restart mantri`.
</details>

<details>
<summary><b>Why not my Bluetooth headset's microphone?</b></summary>

Recording from a Bluetooth headset switches it into "call" mode, and music then sounds poor.
So Mantri uses the built-in microphone. You can still point it at another one with
`MANTRI_MIC_SOURCE`.
</details>

<details>
<summary><b>It says "Didn't understand"</b></summary>

It heard its name, but not a phrase it knows. Say **"Mantri, help"** for the list, or add your
phrase to `mantri-command`.
</details>

<details>
<summary><b>It rejects me after I taught it my voice</b></summary>

Watch the log: each wake shows `speaker <name> <score> ok|REJECTED`. Lower
`MANTRI_SPEAKER_THRESHOLD` (default 0.5) in the service file, or teach it again from where you
usually sit. [tests/CALIBRATION.md](tests/CALIBRATION.md) explains how to pick the number.
</details>

<details>
<summary><b>Can I change its voice?</b></summary>

Yes. Set these in `~/.config/systemd/user/mantri.service`, then restart it:

| Setting | Default | What it does |
|---|---|---|
| `MANTRI_TALKBACK` | `1` | `0` turns spoken replies off |
| `MANTRI_VOICE_SID` | `21` | 20–23 British female, 24–27 British male, 0–19 American |
| `MANTRI_VOICE_SPEED` | `1.1` | Higher is faster |

Hear a voice first:
`~/.local/share/mantri/venv/bin/python ~/.local/share/mantri/mantri.py --say "Hello"`
</details>

<details>
<summary><b>How do I remove it?</b></summary>

```bash
mantri-toggle off
rm ~/.config/systemd/user/mantri.service ~/.local/bin/mantri-{command,toggle,enroll}
rm -rf ~/.local/share/mantri ~/.config/omarchy/plugins/*.mantri
systemctl --user daemon-reload
```
</details>

## 🛠️ For developers

<details>
<summary>Files, tests and calibration</summary>

| File | Role |
|---|---|
| `mantri.py` | The listening service: microphone, speech detection, Whisper, voice match, talk back |
| `mantri-command` | The phrase list, a bash `case` statement. `SPEAK: text` on stdout is read aloud |
| `mantri-toggle`, `mantri-enroll` | On/off switch and voice enrolment |
| `mantri.service` | systemd user unit and its settings |
| `bar-widget/` | The Omarchy bar button |

```bash
PY=~/.local/share/mantri/venv/bin/python
$PY tests/test_wake.py                               # wake-word parsing, no audio
$PY ~/.local/share/mantri/mantri.py --file out.wav   # run a 16 kHz mono recording through the pipeline
```

The test plan and the settings to tune are in [tests/CALIBRATION.md](tests/CALIBRATION.md).
Design choices and the history are in [docs/design.md](docs/design.md).

</details>

<details>
<summary>Credits</summary>

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with Whisper `base.en`, and the
  Silero VAD model it bundles
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) to run the voice models
- [WeSpeaker](https://github.com/wenet-e2e/wespeaker) CAM++ for voice matching
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) for the spoken replies
- [Omarchy](https://omarchy.org/) and Hyprland

</details>

## License

MIT. See [LICENSE](LICENSE).

---

> GitHub [@sudharamachandranrajeev](https://github.com/sudharamachandranrajeev)
