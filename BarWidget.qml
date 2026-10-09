import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// A music note in the bar. Hovering it shows who you are on Nostr and what is
// currently being published; clicking it pauses or resumes publishing.
//
// All state comes from the service — this file only draws it.
BarWidget {
  id: root
  moduleName: "io.github.punkscience.omarchy-scrobble"

  // nf-md-music. Written as a surrogate pair so the source stays ASCII.
  readonly property string glyph: "\udb81\udf5a"

  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null

  // The service is the source of truth, but it is mounted asynchronously, so
  // every read falls back to this widget's own settings entry until it lands.
  readonly property bool publishingEnabled: service
    ? service.publishingEnabled
    : Model.boolSetting(setting("enabled", true), true)
  readonly property bool configured: service ? service.configured : false
  readonly property bool live: service ? service.live : false
  readonly property string statusText: service ? service.statusText : "Starting up"
  readonly property string trackLine: service ? service.trackLine : ""
  readonly property string artist: service ? service.artist : ""
  readonly property string title: service ? service.title : ""
  readonly property string album: service ? service.album : ""
  readonly property string artUrl: service ? service.artUrl : ""
  readonly property string playerName: service ? service.playerName : ""
  readonly property int durationMs: service ? service.durationMs : 0
  readonly property var profile: service ? service.profile : null
  readonly property string npub: service ? service.npub : ""
  readonly property string avatarPath: service ? service.avatarPath : ""

  readonly property bool loginActive: service ? service.loginActive : false
  readonly property var loginMatrix: service ? service.loginMatrix : []
  readonly property int loginSize: service ? service.loginSize : 0
  readonly property bool loginQrAvailable: service ? service.loginQrAvailable : false
  readonly property string loginUri: service ? service.loginUri : ""
  readonly property string loginError: service ? service.loginError : ""
  readonly property bool remoteSigner: service ? service.remoteSigner : false

  readonly property string listenbrainzMode: service ? service.listenbrainzMode : "none"
  readonly property string listenbrainzUser: service ? service.listenbrainzUser : ""
  readonly property bool listenbrainzConnected: service ? service.listenbrainzConnected : false
  readonly property bool lbLoginActive: service ? service.lbLoginActive : false
  readonly property string lbLoginUrl: service ? service.lbLoginUrl : ""
  readonly property bool lbLoginOpened: service ? service.lbLoginOpened : false
  readonly property string lbLoginError: service ? service.lbLoginError : ""

  readonly property string lastfmMode: service ? service.lastfmMode : "none"
  readonly property string lastfmUser: service ? service.lastfmUser : ""
  readonly property bool lastfmConnected: service ? service.lastfmConnected : false
  readonly property bool lfLoginActive: service ? service.lfLoginActive : false
  readonly property string lfLoginUrl: service ? service.lfLoginUrl : ""
  readonly property bool lfLoginOpened: service ? service.lfLoginOpened : false
  readonly property string lfLoginError: service ? service.lfLoginError : ""

  readonly property string durationText: Model.formatDuration(durationMs)
  readonly property string identityText: Model.identityLabel(profile)

  // ------------------------------------------------------------ open state

  property bool popupOpen: false
  property bool triggerHovered: false

  // The popup sits a few pixels below the bar, so the cursor briefly touches
  // neither it nor the trigger on the way across. Closing on a short delay
  // instead of immediately keeps it from flickering shut mid-journey.
  readonly property bool wantOpen: triggerHovered || popup.containsMouse

  // While a QR is on screen the card stays put: it is meant to be looked at
  // through a phone camera, not kept alive by holding the cursor still.
  readonly property bool pinned: loginActive || lbLoginActive || lfLoginActive

  // A sign-in flow owns the whole card: the tabs step aside while it runs.
  readonly property bool cardBusy: loginActive || lbLoginActive || lfLoginActive

  property string activeTab: "now"

  readonly property bool opened: popupOpen
  function open() { closeDelay.stop(); popupOpen = true }
  function close() {
    closeDelay.stop()
    popupOpen = false
    activeTab = "now"
    // Dismissing the card abandons a pairing in progress; leaving an unseen
    // one waiting on the relays would be worse than making you scan again.
    if (loginActive && service) service.cancelLogin()
    if (lbLoginActive && service) service.cancelListenBrainzLogin()
    if (lfLoginActive && service) service.cancelLastFmLogin()
  }
  function toggle() { if (popupOpen) close(); else open() }

  onWantOpenChanged: {
    if (wantOpen) open()
    else closeDelay.restart()
  }

  onPinnedChanged: {
    if (pinned) open()
    else if (!wantOpen) closeDelay.restart()
  }

  Timer {
    id: closeDelay
    interval: 250
    repeat: false
    onTriggered: if (!root.wantOpen && !root.pinned) root.popupOpen = false
  }

  // ------------------------------------------------------------- settings

  function updateSetting(name, value) {
    var entry = { id: moduleName }
    for (var key in settings) if (key !== "id") entry[key] = settings[key]
    entry[name] = value
    settings = entry
    if (bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
      bar.shell.updateEntryInline(moduleName, entry)
  }

  function togglePublishing() {
    updateSetting("enabled", !publishingEnabled)
  }

  // ---------------------------------------------------------------- layout

  implicitWidth: vertical ? barSize : glyphLabel.implicitWidth + Style.space(17)
  implicitHeight: vertical ? glyphLabel.implicitHeight + Style.space(12) : barSize

  Text {
    id: glyphLabel
    anchors.centerIn: parent
    text: root.glyph
    // Accent while something is genuinely being published, plain foreground
    // when idle, faded when publishing is off — readable at a glance.
    color: root.live
      ? Color.accent
      : (root.publishingEnabled ? root.bar.barForeground : Qt.darker(root.bar.barForeground, 1.6))
    opacity: root.publishingEnabled ? 1 : 0.55
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.icon
    renderType: Text.NativeRendering

    Behavior on color {
      enabled: !root.bar || root.bar.foregroundAnimationEnabled
      ColorAnimation { duration: 160 }
    }
    Behavior on opacity {
      NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.MiddleButton

    onEntered: root.triggerHovered = true
    onExited: root.triggerHovered = false
    onClicked: function(mouse) {
      if (mouse.button === Qt.MiddleButton) {
        if (root.service) root.service.refreshProfile(true)
      } else if (!root.configured && root.service) {
        // Nothing to pause yet — the useful action is signing in.
        root.open()
        root.service.startLogin()
      } else {
        root.togglePublishing()
      }
    }
  }

  IpcHandler {
    target: root.moduleName

    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function pause(): void { if (root.publishingEnabled) root.togglePublishing() }
    function resume(): void { if (!root.publishingEnabled) root.togglePublishing() }
    function login(): void { root.open(); if (root.service) root.service.startLogin() }
    function listenbrainzLogin(): void {
      root.open()
      if (root.service) root.service.startListenBrainzLogin()
    }
    function lastfmLogin(): void {
      root.open()
      if (root.service) root.service.startLastFmLogin()
    }
  }

  // ------------------------------------------------------------ hover card

  PopupCard {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    triggerMode: "hover"
    contentWidth: popup.fittedContentWidth(Style.space(340))
    contentHeight: popup.fittedContentHeight(content.implicitHeight)

    // The album cover, washed faintly across the whole card behind the
    // content. Stretches out over the popup padding to the border and is
    // masked to the card's rounded corners — plain clip only knows
    // rectangles. Only once the image has actually loaded; no art, no wash.
    Item {
      anchors.fill: parent
      anchors.margins: -popup.padding
      visible: cardArt.status === Image.Ready
      layer.enabled: true
      layer.smooth: true
      layer.effect: MultiEffect {
        maskEnabled: true
        maskSource: cardArtMask
        maskThresholdMin: 0.5
        maskSpreadAtMin: 0.02
      }

      Image {
        id: cardArt
        anchors.fill: parent
        source: root.artUrl
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        smooth: true
        opacity: 0.25
      }

      // The card surface shape, whose alpha crops the wash to its corners.
      Item {
        id: cardArtMask
        anchors.fill: parent
        visible: false
        layer.enabled: true

        Rectangle {
          anchors.fill: parent
          radius: Style.cornerRadius
          color: "white"
        }
      }
    }

    Column {
      id: content
      anchors.fill: parent
      spacing: Style.space(10)

      // -- listenbrainz sign-in: approve in a browser

      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.lbLoginActive

        Text {
          width: parent.width
          text: "Approve in your browser"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Text {
          width: parent.width
          text: root.lbLoginUrl === ""
            ? "Asking ListenBrainz for a token…"
            : (root.lbLoginOpened
                ? "A ListenBrainz page has opened. Sign in with MusicBrainz and press Approve — this card updates by itself."
                : "Open this page, sign in with MusicBrainz and press Approve:")
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: root.lbLoginUrl !== "" && !root.lbLoginOpened
          text: root.lbLoginUrl
          textFormat: Text.PlainText
          color: Qt.darker(root.bar.foreground, 1.2)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WrapAnywhere
        }

        Row {
          spacing: Style.space(6)

          Button {
            visible: root.lbLoginUrl !== ""
            text: "Open again"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: Quickshell.execDetached(["xdg-open", root.lbLoginUrl])
          }

          Button {
            text: "Cancel"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.cancelListenBrainzLogin()
          }
        }
      }

      // -- last.fm sign-in: approve in a browser

      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.lfLoginActive

        Text {
          width: parent.width
          text: "Approve in your browser"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Text {
          width: parent.width
          text: root.lfLoginUrl === ""
            ? "Asking Last.fm for a token…"
            : (root.lfLoginOpened
                ? "A Last.fm page has opened. Sign in and press Approve — this card updates by itself."
                : "Open this page, sign in and press Approve:")
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: root.lfLoginUrl !== "" && !root.lfLoginOpened
          text: root.lfLoginUrl
          textFormat: Text.PlainText
          color: Qt.darker(root.bar.foreground, 1.2)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WrapAnywhere
        }

        Row {
          spacing: Style.space(6)

          Button {
            visible: root.lfLoginUrl !== ""
            text: "Open again"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: Quickshell.execDetached(["xdg-open", root.lfLoginUrl])
          }

          Button {
            text: "Cancel"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.cancelLastFmLogin()
          }
        }
      }

      // -- pairing: scan this with a phone signer

      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.loginActive

        Text {
          width: parent.width
          text: "Scan with your Nostr signer"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Text {
          width: parent.width
          text: "Open Amber, nsec.app or another NIP-46 signer and scan this code. Your key stays on your phone."
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // Every module is an integer-sized native rectangle, so the code
        // stays crisp and needs no temporary image file. Only dark modules
        // paint; the quiet zone is already baked into the matrix.
        Rectangle {
          id: qrCanvas
          readonly property int moduleSize: root.loginSize > 0
            ? Math.max(3, Math.floor(Style.space(260) / root.loginSize))
            : 0

          visible: root.loginQrAvailable
          width: root.loginSize * moduleSize
          height: width
          color: "white"
          anchors.horizontalCenter: parent.horizontalCenter

          Grid {
            anchors.fill: parent
            columns: root.loginSize

            Repeater {
              model: root.loginQrAvailable ? root.loginSize * root.loginSize : 0

              Rectangle {
                required property int index
                readonly property int matrixRow: Math.floor(index / root.loginSize)
                readonly property int matrixColumn: index % root.loginSize

                width: qrCanvas.moduleSize
                height: qrCanvas.moduleSize
                color: root.loginMatrix[matrixRow].charAt(matrixColumn) === "1"
                  ? "#111111"
                  : "transparent"
              }
            }
          }
        }

        Text {
          width: parent.width
          visible: root.loginUri !== "" && !root.loginQrAvailable
          text: "Install qrencode to show a scannable code. In the meantime, paste this into your signer:"
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: root.loginUri !== "" && !root.loginQrAvailable
          text: root.loginUri
          textFormat: Text.PlainText
          color: Qt.darker(root.bar.foreground, 1.3)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WrapAnywhere
        }

        Text {
          width: parent.width
          visible: root.loginUri === ""
          text: "Preparing…"
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }

        Button {
          text: "Cancel"
          foreground: root.bar.foreground
          bordered: true
          focusable: true
          onClicked: if (root.service) root.service.cancelLogin()
        }
      }

      // -- tabs

      ButtonGroup {
        width: parent.width
        visible: !root.cardBusy
        options: [
          { value: "now", label: "Now playing" },
          { value: "settings", label: "Settings" }
        ]
        value: root.activeTab
        foreground: root.bar.foreground
        accent: Color.accent
        fontFamily: root.bar.fontFamily
        fontSize: Style.font.bodySmall
        focusable: false
        onChanged: function(selected) { root.activeTab = selected }
      }

      // -- now playing

      Column {
        width: parent.width
        spacing: Style.space(10)
        visible: !root.cardBusy && root.activeTab === "now"

        Row {
          width: parent.width
          spacing: Style.space(10)

          Rectangle {
            id: avatarFrame
            width: Style.space(44)
            height: width
            radius: width / 2
            color: Qt.darker(root.bar.foreground, 6)
            border.width: 1
            border.color: Qt.darker(root.bar.foreground, 2.4)

            // The photo is cut into the circle by an alpha mask: plain clip
            // only knows rectangles, so the image would square off the frame.
            Item {
              anchors.fill: parent
              anchors.margins: 1
              visible: root.avatarPath !== ""
              layer.enabled: true
              layer.smooth: true
              layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: avatarMask
                maskThresholdMin: 0.5
                maskSpreadAtMin: 0.02
              }

              Image {
                id: avatarImage
                anchors.fill: parent
                source: root.avatarPath !== "" ? "file://" + root.avatarPath : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                smooth: true
              }

              // A filled circle whose alpha decides where the photo shows.
              Item {
                id: avatarMask
                anchors.fill: parent
                visible: false
                layer.enabled: true

                Rectangle {
                  anchors.fill: parent
                  radius: width / 2
                  color: "white"
                }
              }
            }

            // Shown until an avatar exists — a missing picture should not leave
            // a hole in the card.
            Text {
              anchors.centerIn: parent
              visible: root.avatarPath === ""
              text: root.glyph
              color: Qt.darker(root.bar.foreground, 2)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.heading
            }
          }

          Column {
            width: parent.width - avatarFrame.width - parent.spacing
            spacing: Style.space(2)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              width: parent.width
              text: root.identityText
              textFormat: Text.PlainText
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              text: root.npub !== "" ? Model.shortNpub(root.npub) : "No Nostr identity configured"
              textFormat: Text.PlainText
              color: Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }
        }

        PanelSeparator {
          foreground: root.bar.foreground
        }

        // -- current track

        Row {
          width: parent.width
          spacing: Style.space(10)
          visible: root.trackLine !== ""

          Rectangle {
            id: artFrame
            width: Style.space(44)
            height: width
            visible: art.status === Image.Ready
            color: "transparent"
            clip: true

            Image {
              id: art
              anchors.fill: parent
              source: root.artUrl
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              cache: true
              smooth: true
            }
          }

          Column {
            width: parent.width - (artFrame.visible ? artFrame.width + parent.spacing : 0)
            spacing: Style.space(2)

            Text {
              width: parent.width
              // Plain text, always: track metadata comes from the player and
              // must display literally, never as rich text.
              text: root.title !== "" ? root.title : root.trackLine
              textFormat: Text.PlainText
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: root.artist !== ""
              text: root.artist
              textFormat: Text.PlainText
              color: Qt.darker(root.bar.foreground, 1.3)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              visible: root.album !== "" || root.durationText !== ""
              text: [root.album, root.durationText].filter(function(part) { return part !== "" }).join("  ·  ")
              textFormat: Text.PlainText
              color: Qt.darker(root.bar.foreground, 1.6)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }
        }

        Text {
          width: parent.width
          visible: root.trackLine === ""
          text: "Nothing playing"
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }

        PanelSeparator {
          foreground: root.bar.foreground
        }

        // -- what the plugin is doing about it

        Row {
          width: parent.width
          spacing: Style.space(6)

          Rectangle {
            width: Style.space(7)
            height: width
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: root.live ? Color.accent : Qt.darker(root.bar.foreground, 2)
          }

          Text {
            width: parent.width - Style.space(13)
            text: root.statusText
            textFormat: Text.PlainText
            color: Qt.darker(root.bar.foreground, 1.2)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }
        }

        Text {
          width: parent.width
          visible: root.playerName !== ""
          text: "Source: " + root.playerName
          textFormat: Text.PlainText
          color: Qt.darker(root.bar.foreground, 1.7)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          width: parent.width
          visible: root.configured
          text: "Click to " + (root.publishingEnabled ? "pause" : "resume") + " publishing · middle click refreshes your profile"
          color: Qt.darker(root.bar.foreground, 1.8)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }

      // -- settings: one service per block, buttons stacked so nothing
      // overruns the card.

      Column {
        width: parent.width
        spacing: Style.space(12)
        visible: !root.cardBusy && root.activeTab === "settings"

        Column {
          width: parent.width
          spacing: Style.space(6)

          Text {
            width: parent.width
            text: root.configured ? "Nostr: " + root.identityText : "Nostr: not signed in"
            textFormat: Text.PlainText
            color: Qt.darker(root.bar.foreground, root.configured ? 1.4 : 1.7)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            visible: root.loginError !== ""
            text: root.loginError
            textFormat: Text.PlainText
            color: root.bar.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Button {
            visible: !root.configured
            text: "Sign in with your phone"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.startLogin()
          }

          Button {
            visible: root.configured && root.remoteSigner
            text: "Sign out"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.logout()
          }
        }

        PanelSeparator {
          foreground: root.bar.foreground
        }

        Column {
          width: parent.width
          spacing: Style.space(6)

          Text {
            width: parent.width
            text: root.listenbrainzConnected
              ? ("ListenBrainz: " + (root.listenbrainzUser !== "" ? root.listenbrainzUser : "connected"))
              : "ListenBrainz: not connected"
              textFormat: Text.PlainText
            color: Qt.darker(root.bar.foreground, root.listenbrainzConnected ? 1.4 : 1.7)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            visible: root.lbLoginError !== ""
            text: root.lbLoginError
            textFormat: Text.PlainText
            color: root.bar.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Button {
            visible: !root.listenbrainzConnected
            text: "Connect ListenBrainz"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.startListenBrainzLogin()
          }

          Button {
            visible: root.listenbrainzMode === "session"
            text: "Disconnect ListenBrainz"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.listenbrainzLogout()
          }
        }

        PanelSeparator {
          foreground: root.bar.foreground
        }

        Column {
          width: parent.width
          spacing: Style.space(6)

          Text {
            width: parent.width
            text: root.lastfmConnected
              ? ("Last.fm: " + (root.lastfmUser !== "" ? root.lastfmUser : "connected"))
              : "Last.fm: not connected"
              textFormat: Text.PlainText
            color: Qt.darker(root.bar.foreground, root.lastfmConnected ? 1.4 : 1.7)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            visible: root.lfLoginError !== ""
            text: root.lfLoginError
            textFormat: Text.PlainText
            color: root.bar.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Button {
            visible: !root.lastfmConnected
            text: "Connect Last.fm"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.startLastFmLogin()
          }

          Button {
            visible: root.lastfmMode === "session"
            text: "Disconnect Last.fm"
            foreground: root.bar.foreground
            bordered: true
            focusable: true
            onClicked: if (root.service) root.service.lastfmLogout()
          }
        }
      }
    }
  }
}
