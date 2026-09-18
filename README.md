# Scrobble for Omarchy

An Omarchy plugin that publishes whatever you are listening to, to two places
at once:

- your **Nostr** profile, as a [NIP-38](https://github.com/nostr-protocol/nips/blob/master/38.md)
  user status (kind `30315`, `d=music`)
- your **ListenBrainz** account, as a now-playing and then a listen

Both are signed in from the card: Nostr by scanning a QR code with a phone
signer, so your secret key never touches this machine, and ListenBrainz through
its MusicBrainz approval page. Neither needs a token pasted into a config file.

It puts a music note in the bar. Hover it and you get a card with your Nostr
avatar, your identity, and the track that is currently being published. Click
it to pause or resume publishing.

```
        ┌─────────────────────────────────┐
 ♪  ──▶ │ [avatar]  Darryl G. Wright      │
        │           npub10elfc…zvjptg     │
        │ ─────────────────────────────── │
        │ [art]     Blue Skies            │
        │           Ella Fitzgerald       │
        │           Ella in Berlin · 3:34 │
        │ ─────────────────────────────── │
        │ ● Published to Nostr · ListenBrainz
        │ Source: Spotify                 │
        └─────────────────────────────────┘
```

## Install

Omarchy plugins are unsandboxed code inside the long-running `omarchy-shell`
process, and this one talks to your Nostr signer. Read the source before you
install it.

```bash
omarchy plugin add https://github.com/Punk-Science-Studios-Inc/omarchy-scrobble.git --enable
```

The plugin ID is `io.github.punkscience.omarchy-scrobble`.

### Dependencies

| Requires | For | Notes |
|---|---|---|
| Omarchy 4 (Quattro) shell | The plugin itself | Uses Quickshell, MPRIS |
| `python3` | The signing/publishing helper | Standard library only |
| `qrencode` | Drawing the Nostr sign-in QR | Ships on Omarchy for the Wi-Fi share card. Without it, sign-in falls back to a copyable URI |
| `xdg-open` | Opening the ListenBrainz approval page | Optional; the URL is shown in the card if it is missing |

No pip packages, no compiler, no daemon, no build step. The Schnorr signing,
NIP-44/NIP-04 encryption, the relay WebSocket client, and the ListenBrainz
calls are all in `bin/omarchy-scrobble` using only the Python standard library,
because a plugin is a git clone and cannot install dependencies.

### Remove it

```bash
omarchy plugin remove io.github.punkscience.omarchy-scrobble
```

That takes the widget out of your bar and deletes the plugin folder. It does
not clear your Nostr status, so **Sign out** in the card first if you want that
retracted — or clear it afterwards from any Nostr client.

The plugin writes nothing outside these paths; delete them to remove every
trace:

```bash
rm -rf ~/.local/share/omarchy-scrobble   # signer + ListenBrainz sessions
rm -rf ~/.cache/omarchy-scrobble         # cached profile and avatar
rm -rf ~/.config/omarchy-scrobble        # config file, if you made one
```

Your bar layout lives in `~/.config/omarchy/shell.json`; `omarchy plugin remove`
takes the entry out for you.

## Sign in with your phone

Click the music note and pick **Sign in with your phone**. The card shows a QR
code — scan it with [Amber](https://github.com/greenart7c3/Amber), nsec.app, or
any other [NIP-46](https://github.com/nostr-protocol/nips/blob/master/46.md)
signer, and approve the request.

**Your secret key never touches this machine.** The plugin holds only a
throwaway client key used to talk to your signer; every status event is sent to
your phone to be signed. Losing this laptop does not lose your identity. The
pairing asks for exactly two permissions — read your public key, and sign
kind-30315 status events — so the approval prompt is honest about the scope.

The session is stored at `~/.local/share/omarchy-scrobble/session.json`
(mode 0600) and restored at every login, so this is a one-time step. **Sign
out** in the card clears your Nostr status and forgets the signer.

Already have a `bunker://` URI? Pair without scanning:

```bash
bin/omarchy-scrobble login --bunker "bunker://..."
```

## Connect ListenBrainz

Click **Connect ListenBrainz** in the card. A ListenBrainz page opens, you sign
in with MusicBrainz, press Approve, and the card picks it up on its own. No
token to copy.

A note on how this works, because it is not the obvious route. ListenBrainz is
**not** an OAuth2 provider: its native API authenticates with a user token you
copy off the settings page by hand, and MusicBrainz's own OAuth2 scopes do not
cover submitting listens. What ListenBrainz *does* provide is a
Last.fm-compatible API, and that protocol has a proper desktop sign-in — ask for
a token, send the user to a web page to approve it (which is a MusicBrainz
login), then trade the approved token for a session key. That is the flow used
here. Listens submitted this way land in exactly the same place as native ones.

**Disconnect ListenBrainz** in the card forgets the session, which is stored at
`~/.local/share/omarchy-scrobble/listenbrainz.json` (mode 0600).

## Connect Last.fm

Click **Connect Last.fm** in the card. The helper opens Last.fm's approval
page; sign in and press **Yes, allow access**. The card polls for approval
and stores the resulting session at `~/.local/share/omarchy-scrobble/lastfm.json`
(mode 0600). It stores the session key, not your Last.fm password. **Disconnect
Last.fm** removes the session.

There is nothing to set up first — nowhere to register, nothing to paste.
The plugin ships the API key and shared secret for the registered app it was
built from; Last.fm's desktop flow then mints an account-specific session key
after you approve the request in your browser, and that session key is the
only credential that can submit listens to your account.

Last.fm credentials are sent only to the official HTTPS API origin
(`ws.audioscrobbler.com`). Like every open-source Last.fm client, the app
secret is baked into the plugin — it authorizes this app, not your account.

If you would rather paste a token, put one in the config file as
`listenbrainzToken` — it takes precedence over a session, and uses the native
API instead.

## Configure

A config file is optional — without one you get the default relays and both
sign-ins handled from the card. Create `~/.config/omarchy-scrobble/config.json`
to change relays or paste a token:

```json
{
  "relays": [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net"
  ]
}
```

Check the whole path before you trust it:

```bash
~/.config/omarchy/plugins/io.github.punkscience.omarchy-scrobble/bin/omarchy-scrobble doctor
```

That reports which signer is in use, prints the `npub` it resolves to, connects
to every relay, and validates the ListenBrainz token.

| Key | Meaning |
|---|---|
| `relays` | Relays the status events go to. Defaults to Damus, nos.lol and Primal |
| `connectRelays` | Relays used for the signer handshake — your phone must reach these too. Defaults to `relays` |
| `listenbrainzToken` | A pasted token from <https://listenbrainz.org/settings/>, instead of signing in. Takes precedence over a session |
| `listenbrainzUrl` | For a self-hosted ListenBrainz native API |
| `listenbrainzCompatUrl` | For a self-hosted ListenBrainz Last.fm-compatible API |
| `nsec` | A local secret key, if you would rather not use a phone. See below |
| `nsecCommand` | A shell command that prints that key instead, e.g. `pass show nostr/nsec` |

Either half is optional: with ListenBrainz unconnected the plugin publishes only
to Nostr, and turning **Publish to Nostr** off in the bar settings leaves it
scrobbling only to ListenBrainz.

### Signing with a local key instead

If you have no phone signer, set `nsec` in the config file and `chmod 600` it —
the helper refuses to use a key file others can read. This is the weaker
option: the key sits on disk. A paired phone always wins over a local key, so
sign out first if you want to fall back to one.

This plugin covers the same ground as
[noscrobble](https://github.com/punkscience/noscrobble), which does NIP-38
publishing as a standalone daemon. Use one or the other — running both means
two things fighting over the same status.

### Bar settings

Open the bar settings and pick Scrobble:

| Setting | Default | Meaning |
|---|---|---|
| Publishing enabled | on | Master switch. Turning it off clears your Nostr status |
| Publish to Nostr | on | Set the NIP-38 status |
| Publish to ListenBrainz | on | Send now-playing, then the listen |
| Only this player | empty | Match part of a player name, e.g. `spotify`. Empty follows whatever is playing |
| Settle delay | 5s | How long a track must play before it is published |

## Behaviour

**What gets published.** The status content is `Artist - Title`, with an `r`
tag linking to a YouTube Music search for the track, and an `expiration` tag
set to the end of the track. Expiration matters: if the shell dies mid-song,
relays drop the status on their own rather than leaving you eternally listening
to the same thing.

**When it publishes.** A track has to play for the settle delay (5s by default)
before anything is sent, so skipping through an album costs one publish rather
than ten. Pausing does not retract the status immediately; twenty seconds of
nothing playing does.

**When it scrobbles.** ListenBrainz gets a now-playing at the same time as the
Nostr status, and a listen once the track has actually been played for half its
length or four minutes, whichever comes first. Tracks under 30 seconds are
never submitted. That is ListenBrainz's own rule, and the plugin counts only
real playing time — a track left paused never accrues any.

**Which player.** Whatever is playing, unless you set a player filter. Anything
exposing MPRIS works: Spotify, mpv, Chromium, VLC, Amberol.

## Controls

| Action | Effect |
|---|---|
| Hover | Show identity, current track, publishing state, and both sign-ins |
| Click | Pause or resume publishing — or start sign-in, if you have not yet |
| Middle click | Re-fetch your Nostr profile and avatar |

From a keybind or a script:

```bash
omarchy-shell scrobble status    # what is being published, as JSON
omarchy-shell scrobble publish   # publish the current track now
omarchy-shell scrobble clear     # clear the Nostr status
omarchy-shell scrobble refresh   # re-fetch the profile
omarchy-shell scrobble login     # show the pairing QR
omarchy-shell scrobble logout    # forget the paired signer
omarchy-shell scrobble listenbrainzLogin    # start the ListenBrainz sign-in
omarchy-shell scrobble listenbrainzLogout   # forget the ListenBrainz session
```

## Verify it works

```bash
nak req -k 30315 --author "$(… identity | jq -r .pubkey)" wss://nos.lol
```

NIP-38-aware clients — Damus, Amethyst, Primal — show the status on your
profile. ListenBrainz shows the play at <https://listenbrainz.org/user/you/>.

## Development

```bash
tests/run
```

That runs five suites:

- `tests/model.test.mjs` — the publish/scrobble rules, in Node
- `tests/helper_test.py` — Schnorr signing, bech32, and the NIP-44/NIP-04
  encryption, against the published BIP-340, NIP-19, NIP-44, RFC 8439,
  FIPS-197 and NIST SP 800-38A test vectors
- `tests/relay_test.py` — the relay client, against a local mock relay
- `tests/nip46_test.py` — the whole pairing and remote-signing flow, against a
  mock phone signer, over both encryption schemes
- `tests/listenbrainz_test.py` — the ListenBrainz sign-in and the exact
  submission parameters, against a local stub server

Nothing in the suite touches a public relay or a real account.

```bash
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell Service.qml BarWidget.qml
```

`qmllint` reports the same import warnings for every third-party plugin: it
cannot resolve `qs.Ui` from outside the shell, and it sees this plugin's
`BarWidget.qml` shadowing the base type of the same name. Both are artifacts of
linting outside the shell, not defects.

### Layout

| File | Role |
|---|---|
| `Service.qml` | Watches MPRIS, decides when to publish, drives the helper |
| `BarWidget.qml` | The note in the bar and the hover card. Draws only |
| `Model.js` | The rules — signatures, thresholds, status text. Pure, tested |
| `bin/omarchy-scrobble` | Signing, NIP-46, relays, ListenBrainz. Python stdlib only |

The helper is a normal CLI and can be run by hand; every subcommand prints one
JSON object.

```bash
bin/omarchy-scrobble login              # prints the QR matrix, waits for a scan
bin/omarchy-scrobble identity
bin/omarchy-scrobble profile --refresh
bin/omarchy-scrobble now-playing --artist "Ella Fitzgerald" --title "Blue Skies"
bin/omarchy-scrobble clear
bin/omarchy-scrobble logout
bin/omarchy-scrobble listenbrainz-login --no-browser   # prints the approval URL
bin/omarchy-scrobble listenbrainz-logout
bin/omarchy-scrobble state              # signing + ListenBrainz status, offline
bin/omarchy-scrobble doctor
```

## Privacy and what it touches

- **Publishes** the artist, title, album and length of what you are playing, to
  the relays you configure and to ListenBrainz. That is the whole point, but it
  is public: a NIP-38 status is readable by anyone.
- **Reads** MPRIS on your session bus to see what is playing.
- **Stores** the signer session, the ListenBrainz session, and a cached copy of
  your Nostr profile picture, in the paths listed under [Remove it](#remove-it).
- **Writes** its own entry in `~/.config/omarchy/shell.json` when you toggle
  publishing from the card — the standard mechanism every bar widget uses for
  its own settings, and only on a click. It does not touch anything else in
  your configuration.
- **Never** sends your keys anywhere. With a phone signer they are not on this
  machine at all.

Plugins run unsandboxed inside `omarchy-shell`. Read the source before you
install it.

## License

[The Unlicense](https://unlicense.org/) — this is free and unencumbered
software released into the public domain. Do whatever you like with it.
See [LICENSE](LICENSE).
