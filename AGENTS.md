# omarchy-scrobble

An Omarchy 4 (Quattro) shell plugin. Publishes the currently playing MPRIS
track to Nostr as a NIP-38 status (kind 30315, `d=music`) and to ListenBrainz.

## Shape

| File | Role |
|---|---|
| `Service.qml` | Watches MPRIS, decides *when* to publish, drives the helper |
| `BarWidget.qml` | The bar note and the hover card. Draws only — no logic |
| `Model.js` | The rules: signatures, listen thresholds, status text. Pure |
| `bin/omarchy-scrobble` | Signing, NIP-46, relays, ListenBrainz. Python stdlib |

The split is deliberate: anything worth testing lives in `Model.js` or the
helper, so it can be exercised without a running shell or a playing track.

## Rules

- **The helper stays stdlib-only.** A plugin is a git clone; it cannot install
  dependencies. BIP-340, NIP-44 (ChaCha20+HKDF), NIP-04 (AES-256-CBC) and the
  WebSocket client are hand-rolled for that reason. `qrencode` and `xdg-open`
  are the only external binaries, both optional with a documented fallback.
- **Crypto is pinned to published vectors, never to judgement.** See
  `tests/helper_test.py`. If you touch it, the vectors must still pass.
- **Never name a QML property `enabled` or `state`** on a plugin root; both
  shadow `QQuickItem` members.
- **Tests must not touch a public relay or a real account.** Use the local
  mock relay and stub servers in `tests/`.
- Run `tests/run` and `omarchy plugin validate .` before committing.

## Working on it

```bash
tests/run                                     # all five suites
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell Service.qml BarWidget.qml
```

`qmllint` always reports "Failed to import qs.Ui" and a `BarWidget ->
BarWidget` inheritance cycle for third-party plugins. Both are artifacts of
linting outside the shell; first-party plugins report the same.

To try changes in the running shell:

```bash
cp -r manifest.json *.qml Model.js bin ~/.config/omarchy/plugins/io.github.punkscience.omarchy-scrobble/
omarchy-restart-shell
omarchy-shell scrobble status
```
