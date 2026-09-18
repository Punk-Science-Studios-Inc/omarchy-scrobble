import assert from "node:assert/strict"
import fs from "node:fs"
import vm from "node:vm"

// Model.js is a QML library, so it is loaded the same way QML loads it: as a
// plain script into a bare context. `.pragma library` is a QML directive that
// plain JS does not understand, so it is stripped.
const source = fs
  .readFileSync(new URL("../Model.js", import.meta.url), "utf8")
  .replace(".pragma library", "")
const context = vm.createContext({ Math, Number, String, Array, isFinite })
vm.runInContext(source, context)

// ---------------------------------------------------------------- settings

assert.equal(context.boolSetting(undefined, true), true)
assert.equal(context.boolSetting(null, false), false)
assert.equal(context.boolSetting(true, false), true)
// shell.json is hand-edited, so string forms have to be tolerated.
assert.equal(context.boolSetting("false", true), false)
assert.equal(context.boolSetting("off", true), false)
assert.equal(context.boolSetting("YES", false), true)
assert.equal(context.boolSetting(0, true), false)
// Anything unrecognised must fall back rather than silently reading as false.
assert.equal(context.boolSetting("perhaps", true), true)

assert.equal(context.intSetting(undefined, 5, 0, 60), 5)
assert.equal(context.intSetting("12", 5, 0, 60), 12)
assert.equal(context.intSetting(999, 5, 0, 60), 60)
assert.equal(context.intSetting(-4, 5, 0, 60), 0)
assert.equal(context.intSetting("nonsense", 5, 0, 60), 5)

assert.equal(context.textSetting("  spotify ", ""), "spotify")
assert.equal(context.textSetting("   ", "fallback"), "fallback")
assert.equal(context.textSetting(undefined, ""), "")

// ------------------------------------------------------------------ tracks

// MPRIS hands over an artist as a string or a list depending on the player.
assert.equal(context.artistText("Ella Fitzgerald"), "Ella Fitzgerald")
assert.equal(context.artistText(["Ella Fitzgerald", "Louis Armstrong"]), "Ella Fitzgerald, Louis Armstrong")
assert.equal(context.artistText(["Ella Fitzgerald", "", null]), "Ella Fitzgerald")
assert.equal(context.artistText([]), "")
assert.equal(context.artistText(null), "")

// A title is the one field worth publishing on; radio streams often have
// nothing else.
assert.equal(context.isPublishable("", "Blue Skies"), true)
assert.equal(context.isPublishable("Ella Fitzgerald", ""), false)
assert.equal(context.isPublishable("", "   "), false)

assert.equal(context.statusContent("Ella Fitzgerald", "Blue Skies"), "Ella Fitzgerald - Blue Skies")
assert.equal(context.statusContent("", "Blue Skies"), "Blue Skies")
assert.equal(context.statusContent("Ella Fitzgerald", ""), "Ella Fitzgerald")

// Two different tracks must never collapse onto one signature, or the second
// one is silently never published.
const a = context.trackSignature("A", "B", "C")
assert.notEqual(a, context.trackSignature("A", "B", "D"))
assert.notEqual(a, context.trackSignature("A B", "C", ""))
assert.equal(a, context.trackSignature(" A ", "B", "C"))
assert.equal(context.trackSignature(["A"], "B", "C"), a)

// --------------------------------------------------------------- scrobbling

// ListenBrainz: half the track or four minutes, whichever is sooner.
assert.equal(context.listenThresholdMs(214000), 107000)     // 3:34 -> 1:47
assert.equal(context.listenThresholdMs(600000), 240000)     // 10:00 -> 4:00 cap
assert.equal(context.listenThresholdMs(60000), 30000)       // 1:00 -> 0:30
// Tracks under 30 seconds are never submitted.
assert.equal(context.listenThresholdMs(29999), 0)
assert.equal(context.listenThresholdMs(1000), 0)
// A player that reports no length still scrobbles, on the four-minute rule.
assert.equal(context.listenThresholdMs(0), 240000)
assert.equal(context.listenThresholdMs(undefined), 240000)
assert.equal(context.listenThresholdMs(-1), 240000)

assert.equal(context.shouldSubmitListen(214000, 106999), false)
assert.equal(context.shouldSubmitListen(214000, 107000), true)
assert.equal(context.shouldSubmitListen(214000, 500000), true)
// A jingle must not scrobble no matter how long it is left running.
assert.equal(context.shouldSubmitListen(10000, 999999), false)
assert.equal(context.shouldSubmitListen(0, 239000), false)
assert.equal(context.shouldSubmitListen(0, 240000), true)

// ------------------------------------------------------------------ display

const NPUB = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
const short = context.shortNpub(NPUB)
assert.ok(short.length < NPUB.length)
assert.ok(short.startsWith("npub10elfc"))
assert.ok(short.endsWith("zvjptg"))
assert.equal(context.shortNpub("npub1short"), "npub1short")
assert.equal(context.shortNpub(""), "")

assert.equal(context.identityLabel(null), "Not signed in")
assert.equal(context.identityLabel({ displayName: "Darryl", name: "dgw", npub: NPUB }), "Darryl")
assert.equal(context.identityLabel({ displayName: "", name: "dgw", npub: NPUB }), "dgw")
assert.equal(context.identityLabel({ nip05: "dgw@punk.science", npub: NPUB }), "dgw@punk.science")
assert.equal(context.identityLabel({ npub: NPUB }), short)

assert.equal(context.formatDuration(214000), "3:34")
assert.equal(context.formatDuration(65000), "1:05")
assert.equal(context.formatDuration(9000), "0:09")
assert.equal(context.formatDuration(0), "")
assert.equal(context.formatDuration(undefined), "")

// ------------------------------------------------------------- status line

const base = {
  enabled: true,
  configured: true,
  hasTrack: true,
  playing: true,
  publishing: false,
  publishedNostr: true,
  publishedListenBrainz: true,
  lastError: "",
}

assert.equal(context.statusText(null), "Starting up")
assert.equal(context.statusText({ ...base, enabled: false }), "Publishing paused")
assert.equal(context.statusText({ ...base, configured: false }), "Not configured")
assert.equal(context.statusText({ ...base, hasTrack: false }), "Nothing playing")
assert.equal(context.statusText({ ...base, playing: false }), "Paused")
assert.equal(context.statusText({ ...base, publishing: true }), "Publishing…")
// A phone signer means a prompt is waiting on the handset; say so.
assert.equal(
  context.statusText({ ...base, publishing: true, remote: true }),
  "Waiting for your phone…"
)
assert.equal(context.statusText({ ...base, lastError: "relay refused" }), "relay refused")
assert.equal(context.statusText(base), "Published to Nostr · ListenBrainz")
assert.equal(context.statusText({ ...base, publishedListenBrainz: false }), "Published to Nostr")
assert.equal(context.statusText({ ...base, publishedNostr: false }), "Published to ListenBrainz")
const withLastFm = { ...base, publishedLastFm: true }
assert.equal(context.statusText(withLastFm), "Published to Nostr · ListenBrainz · Last.fm")
assert.equal(context.statusText({ ...withLastFm, publishedNostr: false }), "Published to ListenBrainz · Last.fm")
assert.equal(context.statusText({ ...withLastFm, publishedListenBrainz: false }), "Published to Nostr · Last.fm")
assert.equal(context.statusText({ ...withLastFm, publishedNostr: false, publishedListenBrainz: false }), "Published to Last.fm")
assert.equal(
  context.statusText({ ...base, publishedNostr: false, publishedListenBrainz: false }),
  "Not published"
)

// The precedence above matters: a paused player must not report itself as
// still published.
assert.equal(context.statusText({ ...base, playing: false, publishedNostr: true }), "Paused")

assert.equal(context.isLive(base), true)
assert.equal(context.isLive({ ...base, enabled: false }), false)
assert.equal(context.isLive({ ...base, playing: false }), false)
assert.equal(context.isLive({ ...base, configured: false }), false)
assert.equal(context.isLive(null), false)

console.log("all model checks passed")
