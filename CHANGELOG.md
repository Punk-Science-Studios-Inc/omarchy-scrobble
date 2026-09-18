# Changelog

## 1.2.3

Address the second round of marketplace security review (submission #6347).

- Cap relay WebSocket handshake headers (16 KiB) so a hostile relay cannot
  exhaust memory before the frame limits apply
- Authenticate every relay-supplied event before use: recompute the NIP-01 id
  and check the BIP-340 signature, and require it to match the requested
  filter (author, kind, tags, time range). A forged profile no longer reaches
  the picture fetch
- Confine profile-picture fetches to public HTTPS addresses: reject plain
  HTTP, loops, private/link-local/unspecified addresses, embedded credentials
  and non-443 ports; validate every redirect hop and pin the connection to the
  checked address so a later DNS change cannot redirect it

## 1.2.2

Address the marketplace security review (submission #6347).

- Run the helper through a fixed interpreter (`/usr/bin/python3`) from
  `Service.qml` instead of relying on its `env` shebang and ambient `PATH`
- Read `config.json` and the secret session files through retained no-follow
  descriptors with size, type, owner and link checks; refuse symlinks and
  oversized input rather than following a pathname and stat-ing afterwards
- Write secret session files with randomized exclusive staging and `fsync`
  instead of a predictable `.part` path
- Send ListenBrainz credentials only to first-party HTTPS origins
  (`api.listenbrainz.org`, `listenbrainz.org`); refuse any other configured URL

## 1.2.1

Harden against unbounded memory use from malicious endpoints.

- Cap ListenBrainz HTTP responses at 1 MiB before parsing; reject anything
  oversized or truncated
- Cap WebSocket relay frame payloads at 256 KiB; reject oversized frames
  and defragmented messages before they are retained

## 1.2.0

Connect ListenBrainz from the card, no token to copy.

- **Connect ListenBrainz** opens its approval page, you sign in with
  MusicBrainz and press Approve; the card picks it up on its own
- Uses the Last.fm-compatible API's desktop sign-in, because ListenBrainz is
  not an OAuth2 provider and MusicBrainz's OAuth2 scopes do not cover listen
  submission. Listens land in the same place either way
- A pasted `listenbrainzToken` still works and takes precedence
- **Disconnect ListenBrainz** forgets the session
- `state` reports both sign-ins without touching the network
- A phone signer now reads "Waiting for your phone…" rather than "Publishing…"

## 1.1.0

Sign in with your phone. The plugin no longer needs your secret key.

- Pair a phone signer over [NIP-46](https://github.com/nostr-protocol/nips/blob/master/46.md)
  by scanning a `nostrconnect://` QR code in the bar card — your key never
  touches this machine
- Also accepts a pasted `bunker://` URI
- Speaks both NIP-44 and legacy NIP-04 to the signer, detected per message
- The QR is drawn as native rectangles, so it stays crisp in any theme and
  needs no temporary image file
- Sign out from the card, which clears your Nostr status on the way out
- A local `nsec` still works, and is used only when no phone is paired

## 1.0.0

First release.

- Publishes the current track as a NIP-38 Nostr status (kind 30315, `d=music`)
  with an `expiration` tag matching the track length
- Submits a ListenBrainz now-playing, then a listen once the track has played
  for half its length or four minutes
- Music note bar widget with a hover card showing your Nostr avatar, identity
  and the current track
- Click to pause or resume publishing, middle click to refresh your profile
- Settle delay so skipping through an album does not spam the relays
- Optional player filter
- Self-contained signing helper: Python standard library only, no daemon
