import QtQuick
import Quickshell.Io
import Quickshell.Services.Mpris
import "Model.js" as Model

// Headless half of the plugin. It watches MPRIS, decides when a track is worth
// announcing, and shells out to bin/omarchy-scrobble for the parts QML cannot
// do: Schnorr signing, relay WebSockets, and the ListenBrainz API.
//
// The rules about *when* to publish live in Model.js so they can be tested
// without a running shell. What lives here is the wiring and the state.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // Injected by the shell when the service is mounted.
  property var shell: null
  property var manifest: null

  readonly property string pluginId: "io.github.punkscience.omarchy-scrobble"

  // The plugin folder, stamped onto the manifest by the plugin registry. The
  // resolvedUrl fallback keeps `qml Service.qml` working during development.
  readonly property string pluginDir: {
    if (manifest && manifest.__sourceDir) return String(manifest.__sourceDir).replace(/\/$/, "")
    var url = String(Qt.resolvedUrl("."))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    return url.replace(/\/$/, "")
  }
  readonly property string helperPath: pluginDir + "/bin/omarchy-scrobble"
  readonly property string pythonPath: "/usr/bin/python3"

  function helperCommand(helperArgs) {
    return [pythonPath, helperPath].concat(helperArgs)
  }

  // ------------------------------------------------------------- settings

  // A bar widget's settings live on its shell.json layout entry, so the
  // service reads its own configuration out of the shared config rather than
  // keeping a second copy of it.
  readonly property var settings: settingsEntry()
  readonly property bool publishingEnabled: Model.boolSetting(settings.enabled, true)
  readonly property bool publishNostr: Model.boolSetting(settings.publishNostr, true)
  readonly property bool publishListenBrainz: Model.boolSetting(settings.publishListenBrainz, true)
  readonly property string playerFilter: Model.textSetting(settings.playerFilter, "")
  readonly property int settleSeconds: Model.intSetting(settings.settleSeconds, 5, 0, 60)

  function settingsEntry() {
    var config = shell && shell.shellConfig ? shell.shellConfig : null
    if (!config) return ({})

    var layout = config.bar && config.bar.layout ? config.bar.layout : null
    var sections = ["left", "center", "right"]
    if (layout) {
      for (var s = 0; s < sections.length; s++) {
        var entries = layout[sections[s]]
        if (!Array.isArray(entries)) continue
        for (var i = 0; i < entries.length; i++) {
          if (entries[i] && String(entries[i].id || "") === pluginId) return entries[i]
        }
      }
    }

    var plugins = Array.isArray(config.plugins) ? config.plugins : []
    for (var p = 0; p < plugins.length; p++) {
      if (plugins[p] && String(plugins[p].id || "") === pluginId) return plugins[p]
    }
    return ({})
  }

  // --------------------------------------------------------------- player

  readonly property var players: Mpris.players ? Mpris.players.values : []
  readonly property var activePlayer: selectPlayer()

  readonly property string artist: activePlayer
    ? Model.artistText(activePlayer.trackArtists && activePlayer.trackArtists.length
        ? activePlayer.trackArtists
        : activePlayer.trackArtist)
    : ""
  readonly property string title: activePlayer ? Model.cleanField(activePlayer.trackTitle) : ""
  readonly property string album: activePlayer ? Model.cleanField(activePlayer.trackAlbum) : ""
  readonly property string artUrl: activePlayer ? Model.cleanField(activePlayer.trackArtUrl) : ""
  readonly property string playerName: activePlayer
    ? Model.cleanField(activePlayer.identity || activePlayer.desktopEntry)
    : ""
  readonly property int durationMs: activePlayer && activePlayer.lengthSupported && activePlayer.length > 0
    ? Math.round(activePlayer.length * 1000)
    : 0
  readonly property bool playing: activePlayer ? !!activePlayer.isPlaying : false
  readonly property bool hasTrack: Model.isPublishable(artist, title)
  readonly property string signature: hasTrack ? Model.trackSignature(artist, title, album) : ""
  readonly property string trackLine: Model.statusContent(artist, title)

  function playerMatchesFilter(player) {
    if (playerFilter === "") return true
    var needle = playerFilter.toLowerCase()
    var identity = String(player.identity || "").toLowerCase()
    var entry = String(player.desktopEntry || "").toLowerCase()
    return identity.indexOf(needle) !== -1 || entry.indexOf(needle) !== -1
  }

  // Prefer something actually playing with a title on it; fall back to a
  // paused player so the popup can still show what is loaded.
  function selectPlayer() {
    var playingWithTrack = null
    var anyWithTrack = null

    for (var i = 0; i < players.length; i++) {
      var player = players[i]
      if (!player || !playerMatchesFilter(player)) continue
      if (!Model.isPublishable(player.trackArtist, player.trackTitle)) continue
      if (player.isPlaying) {
        if (!playingWithTrack) playingWithTrack = player
      } else if (!anyWithTrack) {
        anyWithTrack = player
      }
    }
    return playingWithTrack || anyWithTrack || null
  }

  // ---------------------------------------------------------------- state

  property string publishedSignature: ""
  property string listenedSignature: ""
  property double playedMs: 0
  property bool publishing: false
  property bool publishedNostr: false
  property bool publishedListenBrainz: false
  property string lastError: ""

  property var profile: null
  property bool profileLoading: false

  // Pairing with a phone signer. The helper streams its progress, so the QR
  // arrives before the (long) wait for someone to scan it.
  property bool loginActive: false
  property string loginUri: ""
  property var loginMatrix: []
  property int loginSize: 0
  property bool loginQrAvailable: false
  property string loginError: ""
  property string signingMode: "none"
  readonly property bool remoteSigner: signingMode === "remote"

  // ListenBrainz signs in separately, through its own approval page.
  property string listenbrainzMode: "none"
  property string listenbrainzUser: ""
  readonly property bool listenbrainzConnected: listenbrainzMode !== "none"
  property bool lbLoginActive: false
  property string lbLoginUrl: ""
  property bool lbLoginOpened: false
  property string lbLoginError: ""
  readonly property string npub: profile ? String(profile.npub || "") : ""
  readonly property string avatarPath: profile ? String(profile.avatarPath || "") : ""
  readonly property bool configured: profile !== null && npub !== ""

  // Everything the bar widget needs to render, in the shape Model.statusText
  // expects. Kept as one object so the widget has a single thing to bind to.
  readonly property var publishState: ({
    enabled: root.publishingEnabled,
    configured: root.configured,
    hasTrack: root.hasTrack,
    playing: root.playing,
    publishing: root.publishing,
    remote: root.remoteSigner,
    publishedNostr: root.publishedNostr,
    publishedListenBrainz: root.publishedListenBrainz,
    lastError: root.lastError
  })
  readonly property string statusText: Model.statusText(publishState)
  readonly property bool live: Model.isLive(publishState)

  // ------------------------------------------------------------ publishing

  function shouldPublish() {
    return publishingEnabled && configured && hasTrack && playing && (publishNostr || publishListenBrainz)
  }

  function publishNowPlaying() {
    if (!shouldPublish() || nowPlayingProcess.running) return
    if (signature === "" || signature === publishedSignature) return

    publishing = true
    nowPlayingProcess.pendingSignature = signature
    nowPlayingProcess.command = helperCommand([
      "now-playing",
      "--artist", artist,
      "--title", title,
      "--album", album,
      "--duration-ms", String(durationMs)
    ].concat(publishNostr ? [] : ["--no-nostr"])
     .concat(publishListenBrainz ? [] : ["--no-listenbrainz"]))
    nowPlayingProcess.running = true
  }

  // ListenBrainz wants a second submission once the track has genuinely been
  // listened to; Nostr has no equivalent, so this is ListenBrainz-only.
  function maybeSubmitListen() {
    if (!publishingEnabled || !publishListenBrainz || !configured) return
    if (signature === "" || signature === listenedSignature) return
    if (signature !== publishedSignature) return
    if (listenProcess.running) return
    if (!Model.shouldSubmitListen(durationMs, playedMs)) return

    listenedSignature = signature
    listenProcess.command = helperCommand([
      "listen",
      "--artist", artist,
      "--title", title,
      "--album", album,
      "--duration-ms", String(durationMs)
    ])
    listenProcess.running = true
  }

  function clearStatus() {
    if (!configured || publishedSignature === "" || clearProcess.running) return
    publishedSignature = ""
    listenedSignature = ""
    publishedNostr = false
    publishedListenBrainz = false
    if (!publishNostr) return
    clearProcess.command = helperCommand(["clear"])
    clearProcess.running = true
  }

  function refreshProfile(force) {
    if (profileLoading || profileProcess.running) return
    profileLoading = true
    profileProcess.command = force
      ? helperCommand(["profile", "--refresh"])
      : helperCommand(["profile"])
    profileProcess.running = true
  }

  // ----------------------------------------------------- listenbrainz login

  function refreshState() {
    if (stateProcess.running) return
    stateProcess.command = helperCommand(["state"])
    stateProcess.running = true
  }

  function startListenBrainzLogin() {
    if (lbLoginActive || lbLoginProcess.running) return
    lbLoginUrl = ""
    lbLoginOpened = false
    lbLoginError = ""
    lbLoginActive = true
    lbLoginProcess.command = helperCommand(["listenbrainz-login"])
    lbLoginProcess.running = true
  }

  function cancelListenBrainzLogin() {
    if (lbLoginProcess.running) lbLoginProcess.running = false
    lbLoginActive = false
    lbLoginUrl = ""
  }

  function listenbrainzLogout() {
    if (lbLogoutProcess.running) return
    cancelListenBrainzLogin()
    lbLogoutProcess.command = helperCommand(["listenbrainz-logout"])
    lbLogoutProcess.running = true
  }

  function handleListenBrainzLoginLine(line) {
    var parsed = parseResult(line)
    if (!parsed) return

    if (parsed.stage === "auth") {
      lbLoginUrl = String(parsed.url || "")
      lbLoginOpened = parsed.opened === true
      lbLoginError = ""
      return
    }

    if (parsed.stage !== "done") return
    lbLoginActive = false
    lbLoginUrl = ""
    if (parsed.ok) {
      lbLoginError = ""
      // A fresh connection should start reporting straight away rather than
      // waiting for the next track.
      publishedSignature = ""
      refreshState()
      if (shouldPublish()) settleTimer.restart()
    } else {
      lbLoginError = briefly(parsed.error || "ListenBrainz sign-in failed")
    }
  }

  // ------------------------------------------------------------------ login

  function startLogin() {
    if (loginActive || loginProcess.running) return
    loginUri = ""
    loginMatrix = []
    loginSize = 0
    loginQrAvailable = false
    loginError = ""
    loginActive = true
    loginProcess.command = helperCommand(["login", "--name", "Omarchy Scrobble"])
    loginProcess.running = true
  }

  function cancelLogin() {
    if (loginProcess.running) loginProcess.running = false
    loginActive = false
    loginUri = ""
    loginMatrix = []
    loginSize = 0
  }

  function logout() {
    if (logoutProcess.running) return
    cancelLogin()
    logoutProcess.command = helperCommand(["logout"])
    logoutProcess.running = true
  }

  function handleLoginLine(line) {
    var parsed = parseResult(line)
    if (!parsed) return

    if (parsed.stage === "qr") {
      loginUri = String(parsed.uri || "")
      loginMatrix = Array.isArray(parsed.matrix) ? parsed.matrix : []
      loginSize = Model.intSetting(parsed.size, 0, 0, 400)
      loginQrAvailable = parsed.qrAvailable === true && loginSize > 0
      loginError = ""
      return
    }

    if (parsed.stage !== "done") return
    loginActive = false
    loginUri = ""
    loginMatrix = []
    loginSize = 0
    if (parsed.ok) {
      loginError = ""
      refreshProfile(true)
      refreshState()
    } else {
      loginError = briefly(parsed.error || "Sign-in failed")
    }
  }

  function parseResult(text) {
    try {
      var parsed = JSON.parse(String(text || "").trim())
      return parsed && typeof parsed === "object" ? parsed : null
    } catch (error) {
      return null
    }
  }

  // Helper errors are shown in the bar tooltip, so they need to stay short.
  function briefly(message) {
    var text = String(message || "").replace(/\s+/g, " ").trim()
    if (text.length <= 90) return text
    return text.substring(0, 89) + "…"
  }

  // ------------------------------------------------------------- reactions

  // A track change restarts the settle timer rather than publishing straight
  // away: skipping through an album should cost one publish, not ten.
  onSignatureChanged: {
    playedMs = 0
    publishedNostr = false
    publishedListenBrainz = false
    if (signature === "" || signature !== publishedSignature) {
      publishedSignature = ""
      listenedSignature = ""
    }
    if (shouldPublish()) settleTimer.restart()
    else settleTimer.stop()
  }

  onPlayingChanged: {
    if (playing && shouldPublish() && signature !== publishedSignature) settleTimer.restart()
    if (!playing) settleTimer.stop()
  }

  onPublishingEnabledChanged: {
    if (!publishingEnabled) {
      settleTimer.stop()
      clearStatus()
    } else if (shouldPublish()) {
      settleTimer.restart()
    }
  }

  onShellChanged: if (shell) Qt.callLater(function() { root.refreshProfile(false); root.refreshState() })

  Component.onCompleted: if (shell) Qt.callLater(function() { root.refreshProfile(false); root.refreshState() })

  Timer {
    id: settleTimer
    interval: Math.max(0, root.settleSeconds) * 1000
    repeat: false
    onTriggered: root.publishNowPlaying()
  }

  // Counts real listening time for the current track, which is what decides
  // when ListenBrainz gets a listen. It only runs while something is playing,
  // so a paused track never accrues time.
  Timer {
    id: playClock
    interval: 1000
    repeat: true
    running: root.publishingEnabled && root.playing && root.hasTrack
    onTriggered: {
      root.playedMs += interval
      root.maybeSubmitListen()
    }
  }

  // Nothing playing for a while means the status is stale, so retract it.
  // The delay stops a gap between two tracks from clearing and re-publishing.
  Timer {
    id: idleTimer
    interval: 20000
    repeat: false
    running: root.publishedSignature !== "" && (!root.playing || !root.hasTrack)
    onTriggered: root.clearStatus()
  }

  // Profiles change rarely; a slow refresh keeps a new avatar or display name
  // from needing a shell restart.
  Timer {
    interval: 6 * 60 * 60 * 1000
    repeat: true
    running: root.shell !== null
    onTriggered: root.refreshProfile(true)
  }

  // ------------------------------------------------------------- processes

  Process {
    id: nowPlayingProcess
    property string pendingSignature: ""
    running: false
    command: []
    stdout: StdioCollector { id: nowPlayingOut; waitForEnd: true }
    stderr: StdioCollector { id: nowPlayingErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.publishing = false
      var result = root.parseResult(nowPlayingOut.text)
      if (exitCode !== 0 || !result) {
        root.lastError = root.briefly(nowPlayingErr.text || "Could not reach the scrobble helper")
        return
      }
      if (!result.ok) {
        root.lastError = root.briefly(result.error || "Publishing failed")
        return
      }
      root.lastError = ""
      root.publishedSignature = pendingSignature
      root.publishedNostr = !!(result.nostr && result.nostr.ok)
      root.publishedListenBrainz = !!(result.listenbrainz && result.listenbrainz.ok)
      // A track long past its listen threshold when it was published — a
      // resumed track, or a slow relay — should still be submitted.
      root.maybeSubmitListen()
    }
  }

  Process {
    id: listenProcess
    running: false
    command: []
    stdout: StdioCollector { id: listenOut; waitForEnd: true }
    onExited: function(exitCode) {
      var result = root.parseResult(listenOut.text)
      // A failed listen is retried on the next track change rather than here:
      // ListenBrainz deduplicates on listened_at, and hammering it helps
      // nobody.
      if (exitCode !== 0 || !result || !result.ok) root.listenedSignature = ""
    }
  }

  Process {
    id: clearProcess
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true }
  }

  Process {
    id: stateProcess
    running: false
    command: []
    stdout: StdioCollector { id: stateOut; waitForEnd: true }
    onExited: function(exitCode) {
      var result = root.parseResult(stateOut.text)
      if (exitCode !== 0 || !result || !result.ok) return
      if (result.signing) root.signingMode = String(result.signing.mode || "none")
      if (result.listenbrainz) {
        root.listenbrainzMode = String(result.listenbrainz.mode || "none")
        root.listenbrainzUser = String(result.listenbrainz.username || "")
      }
    }
  }

  Process {
    id: lbLoginProcess
    running: false
    command: []
    stdout: SplitParser { onRead: function(line) { root.handleListenBrainzLoginLine(line) } }
    stderr: SplitParser { onRead: function(line) { root.lbLoginError = root.briefly(line) } }
    onExited: function(exitCode) {
      root.lbLoginActive = false
      root.lbLoginUrl = ""
    }
  }

  Process {
    id: lbLogoutProcess
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true }
    onExited: function(exitCode) {
      root.listenbrainzMode = "none"
      root.listenbrainzUser = ""
      root.publishedListenBrainz = false
      root.refreshState()
    }
  }

  Process {
    id: loginProcess
    running: false
    command: []
    // Line-delimited rather than collected: the QR has to reach the popup
    // while the helper is still waiting for the phone.
    stdout: SplitParser { onRead: function(line) { root.handleLoginLine(line) } }
    stderr: SplitParser { onRead: function(line) { root.loginError = root.briefly(line) } }
    onExited: function(exitCode) {
      root.loginActive = false
      root.loginUri = ""
      root.loginMatrix = []
      root.loginSize = 0
    }
  }

  Process {
    id: logoutProcess
    running: false
    command: []
    stdout: StdioCollector { waitForEnd: true }
    onExited: function(exitCode) {
      root.profile = null
      root.publishedSignature = ""
      root.listenedSignature = ""
      root.publishedNostr = false
      root.publishedListenBrainz = false
      root.signingMode = "none"
      root.lastError = ""
      root.refreshProfile(true)
      root.refreshState()
    }
  }

  Process {
    id: profileProcess
    running: false
    command: []
    stdout: StdioCollector { id: profileOut; waitForEnd: true }
    stderr: StdioCollector { id: profileErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.profileLoading = false
      var result = root.parseResult(profileOut.text)
      if (exitCode !== 0 || !result) {
        root.lastError = root.briefly(profileErr.text || "Could not run the scrobble helper")
        return
      }
      if (!result.ok && !result.npub) {
        root.signingMode = "none"
        root.profile = null
        // Not being signed in yet is the normal first-run state, not an error
        // worth shouting about in the bar.
        root.lastError = ""
        return
      }
      root.lastError = ""
      root.signingMode = String(result.mode || "none")
      root.profile = result
      // The identity only arrives now, so anything already playing has been
      // waiting on it.
      if (root.shouldPublish() && root.signature !== root.publishedSignature) settleTimer.restart()
    }
  }

  // ------------------------------------------------------------------- ipc
  //
  // `omarchy-shell ipc call scrobble ...` — enough to drive the plugin from a
  // keybind without opening the popup.

  IpcHandler {
    target: "scrobble"

    function status(): string {
      return JSON.stringify({
        enabled: root.publishingEnabled,
        configured: root.configured,
        mode: root.signingMode,
        listenbrainz: root.listenbrainzMode,
        listenbrainzUser: root.listenbrainzUser,
        npub: root.npub,
        player: root.playerName,
        artist: root.artist,
        title: root.title,
        album: root.album,
        playing: root.playing,
        publishedNostr: root.publishedNostr,
        publishedListenBrainz: root.publishedListenBrainz,
        text: root.statusText
      })
    }

    function publish(): string {
      root.publishedSignature = ""
      root.publishNowPlaying()
      return root.shouldPublish() ? "ok" : "nothing to publish"
    }

    function clear(): string {
      root.clearStatus()
      return "ok"
    }

    function refresh(): string {
      root.refreshProfile(true)
      return "ok"
    }

    function login(): string {
      root.startLogin()
      return "ok"
    }

    function cancelLogin(): string {
      root.cancelLogin()
      return "ok"
    }

    function logout(): string {
      root.logout()
      return "ok"
    }

    function listenbrainzLogin(): string {
      root.startListenBrainzLogin()
      return "ok"
    }

    function listenbrainzLogout(): string {
      root.listenbrainzLogout()
      return "ok"
    }
  }
}
