# Changelog

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
