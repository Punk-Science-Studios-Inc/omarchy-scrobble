// Pure logic for the scrobble plugin.
//
// Nothing here touches QML, Quickshell, or the network, so every rule that
// decides *whether* to publish can be exercised by tests/model.test.mjs
// instead of by playing music and watching the bar.

.pragma library

// Joins the fields of a track signature. A control character, so it cannot
// occur inside an artist, title or album and collapse two tracks into one.
var UNIT_SEPARATOR = "\u001f"

// ---------------------------------------------------------------- settings

function boolSetting(value, fallback) {
  if (value === undefined || value === null) return fallback
  if (typeof value === "boolean") return value
  if (typeof value === "number") return value !== 0
  var text = String(value).trim().toLowerCase()
  if (text === "true" || text === "1" || text === "yes" || text === "on") return true
  if (text === "false" || text === "0" || text === "no" || text === "off") return false
  return fallback
}

function intSetting(value, fallback, min, max) {
  var number = Number(value)
  if (!isFinite(number)) number = fallback
  number = Math.round(number)
  if (min !== undefined && number < min) number = min
  if (max !== undefined && number > max) number = max
  return number
}

function textSetting(value, fallback) {
  if (value === undefined || value === null) return fallback
  var text = String(value).trim()
  return text === "" ? fallback : text
}

// ------------------------------------------------------------------ tracks

function cleanField(value) {
  return value === undefined || value === null ? "" : String(value).trim()
}

// MPRIS reports an artist as either a string or a list; normalise both, and
// drop the empties players like Chromium leave behind.
function artistText(value) {
  if (value === undefined || value === null) return ""
  if (Array.isArray(value)) {
    var parts = []
    for (var i = 0; i < value.length; i++) {
      var part = cleanField(value[i])
      if (part !== "") parts.push(part)
    }
    return parts.join(", ")
  }
  return cleanField(value)
}

function trackSignature(artist, title, album) {
  return [artistText(artist), cleanField(title), cleanField(album)].join(UNIT_SEPARATOR)
}

// A track needs a title to be worth publishing. Radio streams often carry a
// title and no artist, so an artist alone is not enough but a title alone is.
function isPublishable(artist, title) {
  return cleanField(title) !== ""
}

function statusContent(artist, title) {
  var who = artistText(artist)
  var what = cleanField(title)
  if (who === "") return what
  if (what === "") return who
  return who + " - " + what
}

// --------------------------------------------------------------- scrobbling

// ListenBrainz submits a listen after half the track or four minutes,
// whichever comes first, and never for tracks under 30 seconds. A player that
// reports no duration still gets a listen, on the four-minute rule.
function listenThresholdMs(durationMs) {
  var duration = Number(durationMs)
  if (!isFinite(duration) || duration <= 0) return 240000
  if (duration < 30000) return 0
  return Math.min(240000, Math.round(duration / 2))
}

function shouldSubmitListen(durationMs, playedMs) {
  var threshold = listenThresholdMs(durationMs)
  if (threshold <= 0) return false
  return Number(playedMs) >= threshold
}

// ------------------------------------------------------------------ display

function shortNpub(npub) {
  var text = cleanField(npub)
  if (text.length <= 20) return text
  return text.slice(0, 10) + "…" + text.slice(-6)
}

function identityLabel(profile) {
  if (!profile) return "Not signed in"
  var display = cleanField(profile.displayName)
  if (display !== "") return display
  var name = cleanField(profile.name)
  if (name !== "") return name
  var nip05 = cleanField(profile.nip05)
  if (nip05 !== "") return nip05
  return shortNpub(profile.npub)
}

function formatDuration(ms) {
  var total = Math.round(Number(ms) / 1000)
  if (!isFinite(total) || total <= 0) return ""
  var minutes = Math.floor(total / 60)
  var seconds = total % 60
  return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
}

// One line describing what the plugin is doing, for the hover card and the
// bar tooltip. `state` mirrors the Service's own fields.
function statusText(state) {
  if (!state) return "Starting up"
  if (!state.enabled) return "Publishing paused"
  if (!state.configured) return "Not configured"
  if (!state.hasTrack) return "Nothing playing"
  if (!state.playing) return "Paused"
  // With a phone signer there is a prompt waiting on the handset, and saying
  // "Publishing…" leaves you staring at a bar that looks stuck.
  if (state.publishing) return state.remote ? "Waiting for your phone…" : "Publishing…"
  if (state.lastError) return state.lastError
  var targets = []
  if (state.publishedNostr) targets.push("Nostr")
  if (state.publishedListenBrainz) targets.push("ListenBrainz")
  if (targets.length === 0) return "Not published"
  return "Published to " + targets.join(" · ")
}

// The bar glyph is dimmed whenever the plugin is not actively publishing, so
// a glance at the bar tells you whether anything is being shared.
function isLive(state) {
  return !!(state && state.enabled && state.configured && state.hasTrack && state.playing)
}
