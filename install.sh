#!/bin/bash
# Install or update Mantri for the current user. Safe to rerun.
#   ./install.sh
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
share=~/.local/share/mantri

unit=~/.config/systemd/user/mantri.service
fresh=0; [[ -f $unit ]] || fresh=1
mkdir -p "$share" ~/.local/bin ~/.config/systemd/user
[[ -x $share/venv/bin/python ]] || python3 -m venv "$share/venv"
"$share/venv/bin/pip" install -q --upgrade faster-whisper sherpa-onnx

install -m 755 "$here/mantri.py" "$share/mantri.py"
install -m 755 "$here/mantri-command" "$here/mantri-toggle" "$here/mantri-enroll" ~/.local/bin/
install -m 644 "$here/mantri.service" ~/.config/systemd/user/mantri.service

# Models (sherpa-onnx releases): WeSpeaker CAM++ for voice recognition (28 MB),
# Kokoro int8 for talk back (126 MB). Both Apache-2.0.
models=$share/models
releases=https://github.com/k2-fsa/sherpa-onnx/releases/download
mkdir -p "$models"
[[ -f $models/wespeaker_en_voxceleb_CAM++_LM.onnx ]] ||
  curl -fL --progress-bar -o "$models/wespeaker_en_voxceleb_CAM++_LM.onnx" \
    "$releases/speaker-recongition-models/wespeaker_en_voxceleb_CAM++_LM.onnx"
[[ -f $models/kokoro-int8-multi-lang-v1_0/model.int8.onnx ]] ||
  curl -fL --progress-bar "$releases/tts-models/kokoro-int8-multi-lang-v1_0.tar.bz2" | tar xj -C "$models"

# Fetch the Whisper model now rather than on first wake.
"$share/venv/bin/python" -c 'from faster_whisper import WhisperModel; WhisperModel("base.en", device="cpu", compute_type="int8")' 2>/dev/null

# Replace the old "Hey Jarvis" voice-control setup, if present.
if [[ -f ~/.config/systemd/user/voice-control.service ]]; then
  systemctl --user disable --now voice-control.service 2>/dev/null || true
  rm -f ~/.config/systemd/user/voice-control.service ~/.local/bin/voice-command ~/.local/bin/voice-control-toggle
  rm -rf ~/.local/share/voice-control
  echo "Removed the old voice-control (Hey Jarvis) service"
fi
bindings=~/.config/hypr/bindings.lua
if [[ -f $bindings ]] && grep -q 'voice-control-toggle' "$bindings"; then
  cp "$bindings" "$bindings.bak.$(date +%s)"
  sed -i 's/-- Always-listening voice control ("Hey Jarvis")/-- Always-listening voice control ("Mantri")/; s/"Toggle voice control", "voice-control-toggle"/"Toggle Mantri voice control", "mantri-toggle"/' "$bindings"
  echo "Super+Ctrl+J now toggles Mantri"
fi

# Bar toggle (also: omarchy-shell rajeevrama.mantri toggle).
plugin=~/.config/omarchy/plugins/rajeevrama.mantri
mkdir -p "$plugin"
install -m 644 "$here/bar-widget/manifest.json" "$here/bar-widget/Widget.qml" "$plugin/"
if ! grep -q '"rajeevrama.mantri"' ~/.config/omarchy/shell.json 2>/dev/null; then
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
  omarchy bar put rajeevrama.mantri --before omarchy.audio
fi

systemctl --user daemon-reload
# Respect the toggle: an update leaves Mantri off if it was turned off.
if (( fresh )) || systemctl --user is-enabled --quiet mantri.service; then
  systemctl --user enable mantri.service
  systemctl --user restart mantri.service
  echo "Mantri is listening. Logs: journalctl --user -u mantri -f"
else
  echo "Mantri is updated but off; turn it on from the bar or with mantri-toggle on"
fi
