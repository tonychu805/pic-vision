# Desktop client (POC)

Venue owner-facing desktop app -- the first scoped piece from
`STRATEGY.md` §5's "desktop client": **camera discovery/management**.
Everything else in that section (local footage handling, R2 upload,
receiving the cloud pipeline's output, CDN delivery) is not built yet.

Electron + React (Vite), chosen over Tauri for the POC because v1's actual
feature -- ONVIF discovery and RTSP handling -- is Node's ecosystem, not
Rust's; see `progress/` for the fuller stack discussion. All Node/OS access
(ONVIF calls, camera storage) is kept behind `electron/main.js`'s five
`ipcMain.handle` calls and `electron/preload.js`'s matching
`contextBridge` surface -- the renderer never touches Node directly. That
boundary is deliberate: it's what would let a later Tauri port keep
`electron/cameras/*.js` as a Node "sidecar" process instead of a Rust
rewrite.

## Run it

```
cd desktop
npm install
npm run dev       # Vite dev server + Electron window, both hot-reloading
```

`dev:electron` passes `--no-sandbox` -- needed in this dev container because
Electron's setuid sandbox helper isn't set up (`chrome-sandbox` isn't
root-owned+4755 here, and fixing that needs sudo this environment doesn't
have non-interactively). That flag is dev-only; a packaged build on a real
venue-owner OS install doesn't need it and shouldn't ship with it.

It also passes `--remote-debugging-port=9223` -- lets a remote/headless dev
session drive the real renderer (the one with `window.cameraAPI` actually
injected) via the Chrome DevTools Protocol instead of needing to see the
window. Also dev-only; do not ship a packaged build with an open debug
port.

## Visual design

The UI (all 5 pages, the "Nocturne" dark design system -- Inter, blurple
accent `#9184d9`, the specific radii/shadow/spacing tokens) was implemented
from a Claude Design handoff bundle, `desktop-utility-by-claude-design.zip`
(repo root, 2026-09-01) -- read in full and recreated in React per its own
README's instruction, not copied structurally (the source is HTML/CSS/JS
prototype markup with a `{{ }}`-templated runtime, `support.js`, not meant
to ship). `src/index.css`'s tokens and component classes (`.btn`, `.tag`,
`.table`, `.dialog`, ...) are copied verbatim from the bundle's
`styles.css` so they stay traceable to the source values.

Two deliberate deviations from the mockup, both documented in the relevant
file's own comments:
- **The window is genuinely frameless** (`main.js`, `frame: false`) with
  real minimize/maximize/close wired to the title bar's buttons
  (`TitleBar.jsx`, `windowAPI`) -- the mockup drew title-bar chrome as
  static decoration, but since this app has no OS-native fallback title
  bar, those buttons have to actually work or the window can't be closed
  from the UI at all.
- **The mac traffic-light dots are colored red/yellow/green**, not the
  mockup's flat grey -- same reasoning: once they're the only way to close
  the window, real semantic color is load-bearing, not decorative.

## What's real vs. illustrative

**Cameras + camera detail pages are wired to the real backend** -- nothing
shown there is fabricated:

- **Scan for cameras** -- runs two independent methods together, both real:
  - **ONVIF WS-Discovery** (`electron/cameras/discovery.js`) -- a
    multicast probe; only finds cameras that choose to answer it. Filters
    results by the responder's own declared `<wsd:Types>` -- the `onvif`
    npm package itself doesn't, and two real Synology NAS boxes on this
    network were coming back as "cameras" before that filter was added
    (`progress/09.01 progress overview.md` has the full story, including
    the wrong first guess at why).
  - **RTSP port sweep + protocol confirm** (`electron/cameras/networkSweep.js`)
    -- TCP-probes port 554 against every host in the subnet, in parallel,
    then (if the port is open) sends a real RTSP `OPTIONS` request and
    checks for a genuine RTSP response. `OPTIONS` needs no credentials per
    the RTSP spec (RFC 2326 §10.1), so this is a real protocol-level check,
    not a guess, and it's vendor-neutral -- any RTSP camera answers the
    same way regardless of brand. Built because a real camera on this
    network never answered WS-Discovery at all; the sweep found it in ~4s.
    Cards show one of two confidence levels: **"RTSP confirmed"** (a real
    RTSP handshake completed) or **"Possible camera"** (the port's open
    but nothing recognizable as RTSP came back -- could be any service).
    Both are weaker than a WS-Discovery hit's "Sign-in needed", which
    means ONVIF is confirmed present, just needs credentials.
  - Neither one is the mockup's design (it names 6 protocols as
    checkboxes, all illustrative except these two, see Scan Settings).
    Cards from ONVIF discovery render "Sign-in needed" with an inline
    credential form; sweep hits have no known ONVIF path yet, so clicking
    one opens the manual-add dialog pre-filled with its IP instead.
- **Vendor (brand) identification** -- every discovery/sweep hit is looked
  up by MAC address (ARP -- the OS already knows it from the probe/scan
  itself) against the IEEE OUI registry (`oui-data`, bundled locally as a
  dependency, no live network calls, nothing about the venue's devices
  ever leaves the machine; `electron/cameras/vendorLookup.js`). Generic --
  works for any manufacturer with a registered OUI block, not a curated
  per-vendor list. IEEE registrants are legal entity names ("Hangzhou
  Hikvision Digital Technology Co.,Ltd."), so a blanket suffix-stripping
  rule trims common corporate-entity endings (Inc./Ltd./Co.,Ltd./etc.) --
  the same rule for every vendor, not brand-specific shortening. **Model**
  is a different problem: MAC only encodes manufacturer, never model, and
  there's no protocol-generic way to learn a model name before ONVIF
  actually works (`getDeviceInformation()`, already used once a camera is
  added).
- **Add manually** -- for cameras neither method fully resolves (different
  subnet, no ONVIF support, or -- the real BC510 case above -- an ONVIF
  service that exists but 404s at every path checked so far):
  hostname / port / **ONVIF path** (optional, defaults to
  `/onvif/device_service`) / username / password entered directly. Not
  part of the original mockup (which has no manual-add affordance at all)
  -- added because the gap was real, not hypothetical.
- **Connect & add** -- either path calls `cam.connect()` +
  `getDeviceInformation()`; only cameras that actually respond get saved.
  Identity/network/streams panels on the detail page show real
  manufacturer/model/serial/firmware/stream-URI from that call, or "Not
  available" where ONVIF genuinely has no such field (MAC address is never
  fabricated -- ONVIF's `GetDeviceInformation` doesn't return one).
- **Test connection** -- run automatically for every configured camera on
  page load, driving each card's Streaming/Not-answering state and dot
  color for real.
- **Network panel** (sidebar) -- the CIDR shown is this machine's real
  primary interface (`os.networkInterfaces()`, `electron/system.js`), not
  the mockup's hardcoded `10.0.4.0/24` sample.

**Alerts, Credentials, and Scan Settings pages are pixel-matched but not
functional** -- there's no alert monitoring, no stored/tried credential
sets, and no multi-protocol (mDNS/UPnP/vendor-specific) or multi-range
scanning built. Each shows the mockup's own sample data with an honest
"Illustrative" subtitle, and every disabled input/button reflects that
directly rather than silently doing nothing. The Cameras page's bulk
sign-in/sync-time/firmware-update dialog (select mode) is the same --
UI-only, says so in the dialog body, because it depends on the Credentials
page's stored sets which aren't real yet.

Configured cameras persist via `electron-store` (plain JSON,
`~/.config/pic-vision-desktop/cameras.json` on Linux) -- including the
camera's password in plaintext. Fine for local dev, **not** acceptable for
a client shipped to real venues; STRATEGY.md §5 already flags the sibling
problem for RunPod/R2 credentials ("cannot ship `.env` values to external
venue owners") -- whatever secret-storage fix lands for that should cover
this too, not be solved separately.

## Known gaps (not built)

- RTSP-over-wifi reliability: `DECISIONS.md` ADR-030/032 found real frame
  drops/non-monotonic timestamps pulling RTSP over wifi, and preferred
  local (SD-card) recording over a live pull once available. This client
  only proves out *discovery/connectivity* so far -- it doesn't record or
  pull a stream yet, so ADR-032's preference hasn't been designed into it.
- No packaging/signing configured beyond the bare `electron-builder`
  target list in `package.json`.
- Everything past camera management in STRATEGY.md §5's list (local
  encode, R2 upload, CDN delivery) is unbuilt.
