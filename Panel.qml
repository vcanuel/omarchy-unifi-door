import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar button plus a popup with the door camera's current picture. Pictures
// are fetched only while the popup is open, one at a time, so a closed panel
// costs nothing and a slow link never piles requests up.
Panel {
  id: root
  moduleName: "vcanuel.unifi-door"
  ipcTarget: "vcanuel.unifi-door"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property string profile: String(setting("profile", "default"))
  readonly property string wantedCamera: String(setting("camera", ""))
  readonly property int refreshIntervalSec: Math.max(1, Math.min(60, parseInt(setting("refreshIntervalSec", 3), 10) || 3))

  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("bin/unifi-door")).replace(/^file:\/\//, ""))

  property var camera: null
  property string via: ""
  property var error: null
  property double pictureAtMs: 0
  property double nowMs: Date.now()
  property int frame: 0

  readonly property bool needsSetup: !!error && (error.kind === "unconfigured" || error.kind === "auth")
  readonly property string icon: "󰠚"

  function helper(args) {
    return [helperPath, "--profile", profile].concat(args)
  }

  function findCamera() {
    if (cameraProcess.running) return
    cameraProcess.command = helper(["camera", "--camera", wantedCamera])
    cameraProcess.running = true
  }

  function takePicture() {
    if (!camera) { findCamera(); return }
    if (snapshotProcess.running) return
    snapshotProcess.command = helper(["snapshot", "--camera", camera.id])
    snapshotProcess.running = true
  }

  function parse(text) {
    try { return JSON.parse(String(text || "").trim()) } catch (e) { return null }
  }

  function runSetup() {
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation",
      Util.shellQuote(helperPath) + " --profile " + Util.shellQuote(profile) + " setup"
      + "; rc=$?; omarchy-shell -q vcanuel.unifi-door refresh; (exit $rc)"])
    close()
  }

  function ageText() {
    if (pictureAtMs <= 0) return ""
    var s = Math.max(0, Math.round((nowMs - pictureAtMs) / 1000))
    return s < 2 ? "just now" : s + "s ago"
  }

  function handlePress(buttonCode) {
    if (buttonCode === Qt.MiddleButton) takePicture()
    else if (needsSetup) runSetup()
    else toggle()
  }

  onWantedCameraChanged: { camera = null; if (opened) findCamera() }
  onProfileChanged: { camera = null; if (opened) findCamera() }
  onOpenedChanged: if (opened) { nowMs = Date.now(); takePicture() }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { root.error = null; root.camera = null; root.findCamera(); return "ok" }
    function status(): string {
      return JSON.stringify({ opened: root.opened, camera: root.camera, via: root.via, error: root.error,
        finding: cameraProcess.running, fetching: snapshotProcess.running, frame: root.frame })
    }
  }

  Process {
    id: cameraProcess
    stdout: StdioCollector { id: cameraOut; waitForEnd: true }
    onExited: {
      var result = root.parse(cameraOut.text)
      if (result && result.ok) {
        root.camera = result.camera
        root.via = result.via || ""
        root.error = null
        if (root.opened) root.takePicture()
      } else {
        root.error = result && result.error ? result.error : { kind: "http", message: "unifi-door helper failed" }
      }
    }
  }

  Process {
    id: snapshotProcess
    stdout: StdioCollector { id: snapshotOut; waitForEnd: true }
    onExited: {
      var result = root.parse(snapshotOut.text)
      if (result && result.ok) {
        root.error = null
        root.frame += 1
        back.source = Util.fileUrl(result.path) + "?" + root.frame
      } else {
        root.error = result && result.error ? result.error : { kind: "http", message: "unifi-door helper failed" }
      }
    }
  }

  // Next picture once the previous one is in, not on a fixed beat: over the
  // cloud a picture takes about two seconds, which would otherwise overlap.
  Timer {
    interval: root.refreshIntervalSec * 1000
    repeat: true
    running: root.opened
    onTriggered: { root.nowMs = Date.now(); root.takePicture() }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icon
    foreground: root.needsSetup ? root.urgent : root.foreground
    tooltipText: root.opened ? "" : (root.needsSetup ? "UniFi Door: set up" : (root.camera ? root.camera.name : "Door camera"))
    onPressed: function(buttonCode) { root.handlePress(buttonCode) }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (key === "r") root.takePicture()
        else if (key === "s") root.runSetup()
      }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: root.camera ? root.camera.name : "Door camera"
          meta: {
            if (root.error) return root.error.message
            var parts = []
            var age = root.ageText()
            if (age !== "") parts.push(age)
            if (root.via !== "") parts.push("via " + root.via)
            return parts.length ? parts.join(" · ") : "Loading…"
          }
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: root.icon
              color: root.error ? root.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }
          }
          trailingControl: Component {
            Row {
              spacing: Style.space(4)
              PanelActionButton {
                iconText: "󰑐"
                tooltipText: snapshotProcess.running ? "Fetching…" : "Refresh (r)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                opacity: snapshotProcess.running ? 0.5 : 1.0
                onClicked: root.takePicture()
              }
              PanelActionButton {
                iconText: "󰒓"
                tooltipText: "Setup (s)"
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.runSetup()
              }
            }
          }
        }

        // Two images, swapped when the new one has decoded, so the picture
        // never blanks between frames.
        Item {
          id: frameBox
          width: parent.width
          height: Math.round(width * 4 / 3)

          Rectangle {
            anchors.fill: parent
            radius: Style.cornerRadius
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.06)
            visible: front.status !== Image.Ready
          }

          Image {
            id: front
            anchors.fill: parent
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: false
            sourceSize.width: frameBox.width * 2
          }

          Image {
            id: back
            visible: false
            asynchronous: true
            cache: false
            sourceSize.width: frameBox.width * 2
            onStatusChanged: if (status === Image.Ready) {
              front.source = source
              root.pictureAtMs = Date.now()
              root.nowMs = root.pictureAtMs
            }
          }

          Text {
            anchors.centerIn: parent
            visible: front.status !== Image.Ready
            textFormat: Text.PlainText
            text: root.needsSetup ? "Press s to connect to your UniFi console" : (root.error ? root.error.message : "Fetching the picture…")
            color: root.error ? root.urgent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            width: parent.width - Style.space(24)
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }
    }
  }
}
