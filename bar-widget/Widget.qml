import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

// Mantri voice control toggle: shows whether mantri.service is listening and
// starts/stops it on click. Stopping releases the microphone.
BarWidget {
  id: root
  moduleName: "rajeevrama.mantri"

  property bool active: false

  function refresh() { if (!statusProc.running) statusProc.running = true }

  function toggle() {
    root.active = !root.active  // optimistic; the next poll corrects it
    Quickshell.execDetached(["mantri-toggle"])
    settle.restart()
  }

  Process {
    id: statusProc
    command: ["systemctl", "--user", "is-active", "mantri.service"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.active = text.trim() === "active" }
  }

  // Picks up changes from Super+Ctrl+J, systemctl or a crash.
  Timer { interval: 3000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refresh() }
  Timer { id: settle; interval: 1500; onTriggered: root.refresh() }

  // omarchy-shell rajeevrama.mantri toggle   (bindable to a key)
  IpcHandler {
    target: "rajeevrama.mantri"
    function toggle(): void { root.toggle() }
    function status(): string { return root.active ? "on" : "off" }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.active ? "󰍬" : "󰍭"
    useActiveColor: false
    dimmed: !root.active
    tooltipText: root.active
      ? "Mantri listening: say \"Mantri, open firefox\"\nClick to turn off and release the mic"
      : "Mantri off\nClick to start listening"
    onPressed: root.toggle()
  }
}
