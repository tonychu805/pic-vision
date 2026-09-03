# Desktop client / local agent (POC)

Venue owner-facing local app -- per `DECISIONS.md` ADR-071 (2026-09-02),
this is the **local agent** half of a two-part architecture: it owns
everything that has to run on a machine physically at the venue (camera
discovery/management, recording, and eventually calibration/transcode/
upload), while a separate, not-yet-built cloud web app owns everything
that's just data (scheduling, court/venue management, delivery to
players). See `STRATEGY.md` §5 for the full split and `progress/09.02
progress overview.md` for how it was decided. Built so far: camera
discovery/management, recording (`electron/capture.js`), calibration
(`electron/calibration.js`, 2026-09-03), and triggering transcode/upload/
inference/reel-cutting by invoking the existing Python as a subprocess
(`electron/pipeline.js`, PIC-68). Not yet built: receiving the cloud
pipeline's output back for local review, or any connection to the (not
yet existing) web app.

Electron + React (Vite), chosen over Tauri for the POC because v1's actual
feature -- ONVIF discovery and RTSP handling -- is Node's ecosystem, not
Rust's; see `progress/` for the fuller stack discussion. All Node/OS access
(ONVIF calls, camera storage, recording) is kept behind `electron/main.js`'s
`ipcMain.handle` calls and `electron/preload.cjs`'s matching
`contextBridge` surface -- the renderer never touches Node directly. That
boundary is deliberate: it's what would let a later Tauri port keep
`electron/cameras/*.js` (and `capture.js`, `schedule.js`) as a Node
"sidecar" process instead of a Rust rewrite -- or, per ADR-071, what
would let this same backend eventually grow a real local-agent API
surface without restructuring it first.

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

`npm run dev` no longer opens a detached DevTools window automatically
(2026-09-01 -- reported as system-wide mouse lag on every dev launch,
plausibly compositor contention from Electron's own GPU-compositing
surfaces on an already-loaded desktop; removing this one, unconditional
extra Chromium window is a real, verified reduction, though not a
confirmed full fix). Set `OPEN_DEVTOOLS=1` before `npm run dev` if you
actually want the visible window -- the CDP port above already gives
full DevTools-equivalent access without it, which is how this project's
own dev sessions have driven verification all along.

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

## Plain-language pass (2026-09-01)

The mockup's UI text (ONVIF, RTSP, "port sweep," raw IPs as card titles)
reads fine for the person who built the discovery mechanism and badly for
the actual audience -- a venue owner with no technical background. A
walkthrough done as that person, screenshot by screenshot, found five real
problems and all five are fixed:

- **The manual-add form was the biggest blocker.** It asked for an IP
  address, a port, and an "ONVIF path" with no explanation and no help
  finding any of it. `CamerasPage.jsx`'s `ManualAddDialog` now shows
  different copy depending on context (found a device vs. starting blank),
  explains where to find an IP address, and moves Port/path behind an
  "Advanced settings" disclosure most people should never need to open.
- **Cards were labeled by raw IP and protocol name.** `cameraView.js`'s
  `buildCards` now names them by what they are and what to do
  ("Synology camera found" / "Tap to set up"), using the vendor lookup
  (`vendorLookup.js`) already built for exactly this. Confidence-
  appropriate wording matters here: an RTSP-confirmed sweep hit is called
  a "camera," an unconfirmed one a "device" -- it might not be a camera
  at all.
- **The Alerts/Credentials/Settings mock content was a real risk, not
  just unpolished.** It read as real data about the venue (a small gray
  "Illustrative" caption was easy to miss under fully realistic fake
  courts and alerts). All three now show a loud, colored `PreviewBanner`
  and the sample content itself is dimmed with its buttons disabled,
  rather than looking fully live.
- **The sidebar's network panel showed a raw CIDR and interface name**
  ("192.168.1.0/24" / "Interface · enp1s0") as the first thing anyone
  sees. Replaced with "Connected / Scanning this network for cameras";
  the technical detail is still available as a hover tooltip, not the
  headline.
- **There was no guidance once something was found.** A one-line banner
  now appears above the grid ("We found something that might be your
  camera below — tap it to finish setting it up") the moment an
  unconfigured card exists.

Verified via the same CDP-driven walkthrough used throughout this
project's other real testing -- actual screenshots of the actual running
app, not a description of the intended change.

## What's real vs. illustrative

**Cameras + camera detail pages are wired to the real backend** -- nothing
shown there is fabricated:

- **Scan for cameras** -- runs two independent methods together, both
  real. **Manual only, never automatic** (operator's call, 2026-09-03,
  reversing the auto-scan-on-launch behavior this page used to have) --
  `startScan` now only ever fires from an explicit "Scan"/"Scan again"
  click, not on mount. State still survives switching tabs regardless
  (2026-09-01 fix, unrelated to when a scan starts): `CamerasPage` used to
  unmount whenever nav left it and remount fresh on return, silently
  wiping its scan results (reported as "the scanning screen seems
  stateless... the cameras are gone," real, especially visible with zero
  configured cameras where the page showed nothing at all). `App.jsx` now
  keeps `CamerasPage` mounted permanently (CSS `display: none` when
  hidden, not unmounted), so its state -- scan results, select-mode, an
  open manual-add dialog, all of it -- survives switching tabs for free.
  A separate, cheap effect (keyed on an `active` prop) re-reads the
  *configured* camera list every time the tab becomes visible again
  (also on the very first mount, so already-added cameras still show up
  immediately despite no scan running), since that can genuinely change
  elsewhere (a rename/removal on a camera's own detail page) while this
  tab was hidden -- that's a local store read + per-camera connection
  re-check, not the real network scan.
  - **ONVIF WS-Discovery** (`electron/cameras/discovery.js`) -- a
    multicast probe; only finds cameras that choose to answer it. Filters
    results by the responder's own declared `<wsd:Types>` -- the `onvif`
    npm package itself doesn't, and two real Synology NAS boxes on this
    network were coming back as "cameras" before that filter was added
    (`progress/09.01 progress overview.md` has the full story, including
    the wrong first guess at why). **That filter had a real latent bug,
    found the same day it first "worked":** it cross-referenced a `Set`
    of confirmed device URNs against `Discovery.probe()`'s resolved list,
    but `cam.urn` is `undefined` on this version of `onvif`'s Cam
    objects -- so the check degenerated into "did *any* device pass,"
    which only happened to filter correctly while zero real cameras had
    ever answered a scan. The moment a real camera (a TP-Link Tapo C200)
    finally responded alongside the NAS boxes, its pass silently
    re-admitted them too. Fixed by building the confirmed list directly
    from the event data instead of cross-referencing anything afterward
    -- verified against the real network twice, including a repeat scan
    to rule out a one-off. **A second real bug surfaced verifying the
    auto-scan fix below:** one physical device commonly answers a single
    probe more than once (multiple interfaces, or the probe going out
    more than once), and building the list from raw events lost the
    deduplication `Discovery.probe()`'s own resolved list had apparently
    been doing for free -- the same Tapo C200 showed up twice in one
    scan. Fixed by keying the accumulated device map by `cam.hostname`
    instead of pushing every event to an array.
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
  - **One workflow to connect any not-yet-configured camera, however it
    was found** (2026-09-01, unified from two): clicking a card from
    either method used to open two genuinely different UIs -- a
    WS-Discovery hit opened a narrow inline sign-in form on its own
    detail page (ONVIF-only, no fallback if it failed), while a sweep
    hit opened the fuller manual-add dialog with the full RTSP fallback
    ladder. Different capability depending on how a camera happened to
    be found wasn't a deliberate distinction (operator: "i want one
    single workflow") -- both now open the same manual-add dialog,
    pre-filled with whatever's already known (hostname always; the real
    ONVIF port too for a WS-Discovery hit, e.g. a Tapo C200's 2020,
    instead of defaulting to 80 and asking the user to find the real one
    under "Advanced settings"). `CameraDetailPage.jsx` is simpler for it
    -- it only ever shows a *configured* camera now, so its own
    `isDiscoveredOnly` branch and inline sign-in form are gone entirely,
    not just unused. **A real regression from the port pre-fill above,
    caught the same day within one real use:** the pre-fill logic used
    `device.port` for *any* card, but that field means something
    different depending on discovery method -- a WS-Discovery hit's is
    the real ONVIF port, a sweep hit's is the RTSP port it was found on
    (554), not an ONVIF port at all. Passing 554 through as the ONVIF-
    connect port made the initial ONVIF attempt send an HTTP/SOAP request
    at a raw RTSP port, which hangs instead of failing fast -- reproduced
    live on the Synology BC510 (a stuck "Connecting…" that used to fail
    over to the RTSP ladder in about a second). Fixed by only using
    `device.port` for `kind === "discovered"` cards; sweep hits keep the
    plain 80 default.
  - **Dismiss a not-yet-configured card without signing in first**
    (2026-09-01 -- "even before signing in, i should still be able to
    delete a detected camera," e.g. a device that turns out not to be
    the operator's camera at all). A small × on the card
    (`CameraCard.jsx`, hidden during select-mode -- the checkbox takes
    that spot instead) removes it from `discovered`/`sweepHits`.
    Session-local, not persisted anywhere: the device is still really on
    the network, so it's expected to reappear on the next "Scan again" --
    there's no configured record to delete, only a card to hide for now.
  - **The card's ONVIF/RTSP badge is gone, not relabeled** (2026-09-01,
    operator: "i'd rather not having a label on the card, but rather
    just display the detail information as is"). It was never actually
    naming a streaming protocol choice -- every camera streams over RTSP
    regardless of how it was connected (ONVIF just adds device metadata
    on top, via `GetDeviceInformation`), so a two-value "ONVIF"/"RTSP"
    pill implied a distinction that doesn't exist at the video layer.
    Removed outright rather than relabeled -- the subtitle line already
    shows the real thing (actual vendor/model, or an honest "Camera"/
    "Not available" when unknown), so there was nothing worth encoding
    into a second badge.
  - **IP address and vendor/model dropped from the card entirely**
    (2026-09-01, operator: "hide ip and camera information on the card
    too" -- following the detail page's own collapse-by-default a couple
    changes earlier). A configured card now shows just its name and
    connection state; the same detail is still there, one tap away,
    behind that camera's own "Show camera details" toggle. Kept for
    discovered/sweep cards specifically: their subtitle line is an
    action prompt ("Tap to sign in," "Tap to set up"), not device
    information, and removing it would leave a card with no explanation
    of what tapping it actually does.
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
- **RTSP fallback ladder, automatic** (`electron/cameras/rtspProbe.js`,
  `store.js`'s `addCameraViaRtsp`) -- the real payoff of the BC510
  investigation: its ONVIF service turned out to be switched off entirely
  (a Synology-specific "Operation Mode" setting, `svs`/`onvif`/`c2`), yet
  its actual video stream worked the whole time at `rtsp://host:554/1` --
  found by reading the camera's own client JS, then confirmed for real
  with `ffprobe` (2880×1620 H.264 + audio) before building anything.
  ONVIF metadata (model/serial/firmware) isn't actually load-bearing for
  this product -- it needs a stream to cut highlights from, not a model
  name -- so when the manual-add form's ONVIF attempt fails, it now
  automatically tries a short, generic list of common stream paths (`/1`,
  `/2`, `/live`, ... -- deliberately not a per-vendor path table) with the
  same credentials, verified by a real RTSP `DESCRIBE` exchange (Digest
  auth implemented from scratch here, since unlike `OPTIONS` it isn't
  credential-free). A subtle real bug caught before trusting it: the
  first version opened a fresh TCP connection per request and failed
  against a real server (LIVE555) that ties its auth nonce to the
  connection it was issued on -- fixed by holding one connection across
  both the challenge and the authenticated retry. If no common path
  works, the dialog offers a raw-RTSP-URL field as the true last resort
  (found in the camera's own app, works for anything the generic list
  misses). A camera added this way shows "Not available (added without
  ONVIF)" for model/serial/firmware rather than silently leaving them
  blank -- real end-to-end result on the BC510: added and streaming,
  same friction as a normal attempt (IP + username + password), zero
  manual path entry needed.
- **Connect & add** -- either ONVIF or the RTSP fallback path verifies
  before saving; only cameras that actually respond get saved.
  **Idempotent by hostname** (2026-09-01, real bug fix) --
  `addCamera`/`addCameraViaRtsp` (`electron/cameras/store.js`) used to
  push a new entry on every successful call with no check against what's
  already configured, so two genuine successful add attempts for the
  same physical camera (a slow first request plus a retry, a double-
  click, reopening the dialog without realizing the first one already
  worked) created two separate entries for it -- found for real (two
  "Synology camera"/"Court 1" entries at the same IP) right after the
  credential-workflow unification made a retry likely. Both functions
  now check for an existing camera at the same hostname first and
  return it unchanged instead of re-verifying and duplicating.
  Identity/network/streams panels on the detail page show real
  manufacturer/model/serial/firmware/stream-URI from ONVIF's
  `GetDeviceInformation`, or "Not available" where ONVIF genuinely has no
  such field (MAC address is never fabricated -- ONVIF doesn't return
  one) -- an RTSP-added camera gets manufacturer from the MAC/vendor
  lookup instead and says so for the rest. **Collapsed by default**
  (2026-09-01, operator's call) behind a "Show camera details" toggle --
  real data (raw stream URLs, ONVIF paths, MAC/serial fields that are
  often just "Not available"), but genuinely technical, not something a
  venue owner needs in front of them every time they open a camera. Same
  disclosure pattern as `ManualAddDialog`'s "Advanced settings"
  elsewhere in this app, not a new one. **A real crash bug here, found
  and fixed 2026-09-01:** signing in to a WS-Discovery-found camera
  directly from its detail page (`CameraDetailPage.jsx`'s inline
  `SignInInline` form -- distinct from the manual-add dialog's flow,
  which was already fine) successfully saved the camera but then crashed
  the whole app to a blank white screen, because the hand-built "now
  configured" card object it switched to was missing every field
  `cardVisuals()`/`STATE_META` expect (only `key`/`kind`/`camera` were
  set), and that lookup has no fallback. Went unexercised all session
  because it needed a camera that both answers WS-Discovery *and* signs
  in via plain ONVIF with no fallback needed -- the first one to do both
  was a real TP-Link Tapo C200, added this same day. Fixed by extracting
  the one correct card-building shape (`cameraView.js`'s new
  `configuredCard()`) and using it in both places that build a
  "configured" card, instead of `buildCards()`'s version being the only
  correct one. Verified against the real network: removed the C200,
  rediscovered it, redid the actual sign-in through the real form fields
  (not a shortcut), confirmed the app rendered its full detail page
  afterward instead of going blank.
- **Test connection** -- run automatically for every configured camera on
  page load, driving each card's Streaming/Not-answering state and dot
  color for real. Branches on how the camera was added (`connectionType`)
  -- an RTSP-added camera is re-checked with the same RTSP `DESCRIBE`
  exchange it was added with, not an ONVIF call it was never going to
  answer.
- **Rename camera** (2026-09-01) -- click a configured camera's name on
  its detail page to edit it in place, `Enter`/blur saves, `Escape`
  cancels. Name only, deliberately -- connection details (hostname/port/
  path/credentials) aren't editable yet; changing those would need the
  same re-verification `addCamera`/`addCameraViaRtsp` already do before
  saving, which `renameCamera` doesn't attempt. Preserves the card's
  existing connection state across a rename (doesn't reset to
  "Checking…" -- a rename doesn't change whether the camera is actually
  reachable). Verified against a throwaway dummy camera, not a real one:
  renamed through the real inline editor, confirmed the new name on disk
  and reflected back on the Cameras grid, cleaned up afterward.
- **Network panel** (sidebar) -- the CIDR shown is this machine's real
  primary interface (`os.networkInterfaces()`, `electron/system.js`), not
  the mockup's hardcoded `10.0.4.0/24` sample.
- **Remove camera** (camera detail page, 2026-09-01) -- the backend
  (`cameraAPI.remove`) existed from the start, but no button ever called
  it; a venue owner who added a camera by mistake had no way to take it
  back out. Two-step (an inline "remove this camera and its schedule?"
  confirm, not a first-click delete or the OS's native `window.confirm`
  dialog, which would look out of place against this app's own custom
  chrome) -- removing a camera also removes its schedule (`PIC-66`'s
  `electron/schedule.js` sessions), same as it already did when this was
  callable only via the IPC layer directly. Verified against a throwaway
  dummy camera entry, not the operator's real one: added directly to the
  on-disk store, removed through the new UI, confirmed gone from both the
  list and disk, confirmed the real camera and its own schedule were
  untouched throughout.

**Schedule page is real, but config-only** (`electron/schedule.js`,
`src/pages/ScheduleOverviewPage.jsx` + `ScheduleEditorPage.jsx`,
`src/components/WeekGrid.jsx` + `DayActivityStrip.jsx`, 2026-09-01,
reworked same day from an earlier flat-cell version) -- per-camera
**sessions**, not just "hours on/off": each is a distinct object (day of
week + start/end hour, minimum block size one hour), so a 1-2pm booking
and a back-to-back 2-4pm booking for someone else stay two separate
sessions rather than merging into one indistinguishable 1-4pm block --
the point being that each session is meant to become its own highlight
job once real capture/detection exist, and a flat "is this hour active"
set can't represent that boundary at all. Drag across the grid to book a
session spanning exactly the hours dragged; click an existing session
(on the grid, or its delete button in the list alongside the grid) to
remove it. Each session renders as **one real rectangle**, not a stack
of per-hour cells: `WeekGrid.jsx` splits an interaction layer (168
plain, always-neutral cells handling all the click/drag hit-testing,
unchanged) from a `pointer-events: none` visual overlay on top -- one
absolutely-positioned `<div>` per session, sized to its full span
(`spanRect()`: a 2-hour booking is one 34px-tall shape with its own
single `border-radius`, not two 16px squares glued together). A stack
of individually-rounded cells still reads as multiple pieces even with
zero gap between them -- rounded corners repeat at every hour boundary
-- so a per-cell approach (tried twice: a border at each session's
start/end hour, then a gap-closing "bridge" rect between same-session
cells) could get the *spacing* right but never the *shape* right.
Verified geometrically via `getBoundingClientRect`, not just eyeballed:
a real continuous 2-hour booking measures as exactly one 34px element
(not two 16px ones), two separate touching 1-hour bookings measure as
two distinct 16px elements with a real 2px gap between them, and the
hour-label gutter still lines up with its row. No per-session label/name
in the UI yet (not needed yet) --
`schedule.js`'s `label` field and rename IPC call still exist, just
unused by this page for now. Booking a range that overlaps existing
sessions trims or splits them rather than silently double-booking
(`electron/schedule.js`'s `subtractRange`) -- verified directly, not
just via the UI: a session added in the middle of an existing one
correctly splits it into two independent remainders.
**What this doesn't do yet: actually start or stop anything.** There's no
real capture/recording process in this app at all (`PIC-66`,
`STRATEGY.md` §5's "Local stream/footage management" bullet) -- this is
the per-session boundary a future capture scheduler / highlight-job
runner would read, built and verified now (real coordinate-based drags
via CDP, persistence round-tripped through `scheduleAPI`, confirmed
against the on-disk JSON) so it's ready to wire up rather than
redesigned later. One real bug caught before shipping: the overview's
per-day activity bars used a linear 0-24h height scale that rounded
anything under ~6h/day to the same pixel height as 0h/day (color
differed, height didn't) -- caught by reading the actual rendered
`style.height` values via CDP, not just checking the numbers/colors
looked right, fixed with a higher floor for any nonzero day.

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

## Recording (`electron/capture.js`, 2026-09-02 -- PIC-66)

Real, not a stub: a "Start recording" / "Stop recording" control on each
configured camera's detail page spawns `ffmpeg` and pulls the camera's
actual RTSP stream to local `.mkv` segments -- the first thing in this
whole client that pulls live video rather than just verifying a stream
exists. Command shape is exactly `TECH_SPEC.md` §1.2's spec: `-c copy`
(stream copy, no re-encode -- sidesteps `PIC-67`'s GPU-encoder question
entirely for this step), 10-minute segments (a crash or Wi-Fi drop costs
one segment, not the whole recording, per the real frame-drop testing in
`DECISIONS.md` ADR-030/032), `-use_wallclock_as_timestamps 1` (the
camera's own RTP timestamps are unreliable/non-monotonic, same ADR).
Stopping is always a clean `SIGINT`, never a hard kill (ADR-031 found
that corrupts the output container) -- including on app quit, via a
`before-quit` handler that waits for any active recording to actually
finish stopping first.

**One real bug found and fixed before this was trusted, not by reading
the spec and assuming it was right:** `TECH_SPEC.md`'s own example
command uses a `.mp4` filename, but its own prose two lines later says
`pcm_alaw` audio requires MKV, since MP4 has no codec tag for it -- and
the Tapo C200 streams exactly that. Copying the example literally
produced a real, silent-looking failure (`Could not find tag for codec
pcm_alaw... Could not write header`, 0-byte output file) the first time
this ran against a real camera. Fixed by using `.mkv` -- confirmed
against *two* real cameras with *different* audio codecs (the C200's
`pcm_alaw`, the Synology's `pcm_mulaw`), both producing valid,
ffprobe-clean files.

**A second real gap fixed the same way:** the first version returned
"recording started" the instant `ffmpeg` was spawned, so a fast failure
(like the one above) reported success and then silently reverted to
"Start recording" seconds later with no explanation -- confusing, reads
like a UI bug rather than a diagnosable error. Fixed with a 2-second
startup grace period before trusting a start actually worked; a fast
`ffmpeg` exit within that window now rejects with the real error instead.

Trigger is a manual button only (operator's call, 2026-09-02) -- not
tied to the Schedule page's booked sessions yet, even though the
Schedule page's own copy already promises that ("each booking becomes
its own highlight reel once automatic capture is built"). A manual
button was simpler to get right first; wiring it to sessions is the
natural next step, not a separate mechanism.

Recordings save to `~/pic-vision-recordings/<camera name>/<timestamp>/`
-- outside Electron's own userData directory, deliberately, since these
files need to be findable by a human (and eventually fed into the
Python pipeline in this repo), not buried in an app-private directory.

## Cloud pipeline (`electron/pipeline.js`, 2026-09-02 -- PIC-68)

Each camera's detail page now has a "Cloud pipeline" panel below Recording:
a calibration control (below) and a "Send to cloud" row per past recording
(`capture.js`'s new `listRecordings`, which just lists what's on disk under
`~/pic-vision-recordings/`, since nothing tracked recordings anywhere
before this).

**Calibration (`electron/calibration.js`, 2026-09-03).** Originally scoped
(PIC-68) to just a native file picker for an existing `calib.json` -- not a
calibration flow. Superseded the same day: `CalibrationControl`
(`CameraDetailPage.jsx`) now takes a real snapshot from the camera's own
live stream (`capture.js`'s `grabSnapshot`, `ffmpeg -frames:v 1` against the
RTSP URL) and opens a modal where the operator clicks the 12 court
intersections + 2 net-tape points directly on the image -- the same
click-collection flow `webapp/templates/calibrate.html`'s browser UI
already offers, ported into React rather than reimplemented from scratch.
The 14 points are handed to `cloud_pipeline/save_calibration.py` (new),
which imports `calibrate.py`'s `solve_assignment`/`compute_calibration`
to fit the homography -- the actual math stays in Python and gets invoked
as a subprocess, per ADR-071, not ported to JS. The result is written to
`~/pic-vision-recordings/<camera>/calib.json` (a sibling of that camera's
recording folders, not nested in one -- a calibration outlives any single
session) and remembered via `store.js`'s `calibPath`, same field PIC-68
already used. The native file picker (`system.js`'s `pickCalibFile`) stays
as a secondary "Import file…" option, for a calibration produced elsewhere
(`cloud_pipeline/setup_venue_calibration.py`, or reusing another camera's
click pass for the same physical mount).

**Verified:** `save_calibration.py`'s homography fit against a real,
already-scored calibration (`calib/IMG_7743_calib.json`) -- feeding its
recorded `image_points`/`net_image_points` back through the new script
reproduced its exact `reprojection_rmse_ft` (0.845 ft) and `point_names`,
confirming the port introduced no drift from `calibrate.py`'s own math.
`grabSnapshot` verified against a real configured camera (a live RTSP
pull, decoded and confirmed valid via `cv2.imread`) -- **not** against
footage of an actual court, since neither camera currently configured on
this machine is pointed at one (a live-snapshot test against the real
"Court 1" camera briefly exposed an unrelated private frame from its
current, non-court position before this was noticed -- the file was
deleted immediately; see the operator's own note for why the click-modal
UI itself has not been exercised end-to-end against a real snapshot the
same way). `vite build` clean; `pytest -q --ignore=archive` unaffected
(132 passed -- `archive/`'s own pre-existing, unrelated collection error
still blocks a bare `pytest -q`, same as before this change).

"Send to cloud" spawns `cloud_pipeline/run_desktop_job.py` -- concatenating
`capture.js`'s 10-minute segments into one file first (`ffmpeg concat`,
stream copy, same `-c copy` capture already uses) -- which itself just
calls `webapp/pipeline.py`'s `run_cloud_job(job_dir)`/`cancel_job(job_dir)`
on a background thread. This is the ADR-071 "reuse the existing Python,
don't reimplement R2 upload/RunPod dispatch/reel-cutting in JS" directive
in its most literal form: `pipeline.js` itself does nothing but spawn a
process, poll the same `status.json` the Flask dashboard already writes,
and relay it to the UI. Cancel sends `SIGINT` (never a hard kill, same
convention as `capture.js`/ADR-031) -- the Python wrapper's own signal
handler calls `cancel_job()`, which terminates any RunPod pod already
created so a cancelled job can't keep billing unattended.

**One real bug found and fixed while wiring this, not assumed away:**
`cloud_pipeline/run_cloud_job.py`'s missing-calibration guard raises
`SystemExit` (reasonable for its own bare-CLI use -- a clean one-line
message instead of a traceback), but `webapp/pipeline.py`'s
`run_cloud_job(job_dir)` only caught `Exception`, which `SystemExit`
isn't a subclass of. A job with no calibration silently escaped that
`except` block, and `status.json` was left stuck at `stage="drift_check"`
forever instead of ever reaching `stage="error"` -- confirmed by actually
running the failure case against this repo (a missing-calibration path,
below), not by reading the code and assuming the existing
`except Exception` was broad enough. This was a live bug in the Flask
dashboard's cloud-job route too, not something new to this caller --
fixed at the shared `except (Exception, SystemExit)` in `webapp/pipeline.py`.

**Not yet exercised against real cloud/GPU resources.** Verified so far:
the missing-calibration failure path end-to-end (subprocess spawn ->
`job.json` -> `status.json`/`log.txt` -> `stage="error"` surfaced back
through `pipelineAPI.status`), plus a renderer build. A full run that
actually uploads to R2 and creates a billed RunPod pod has not been run
from the desktop client -- that needs real per-venue credentials and
should be a deliberate, confirmed test given the cost, not something
exercised casually while wiring the plumbing.

## Sample-clip camera source (`electron/cameras/store.js`'s `addCameraFromSampleClip`, 2026-09-03)

`ManualAddDialog`'s "Add" flow (`CamerasPage.jsx`) now offers a dropdown:
"a live camera" (the existing ONVIF/RTSP flow, unchanged) or "a sample clip"
-- upload a local video file instead of connecting to anything. Built
directly in response to neither camera on this network reliably being
pointed at a real court, which made testing calibration/the cloud pipeline
either impossible or a real privacy risk (see the recording section's
own note on the day's live-snapshot incident).

A sample-clip camera (`connectionType: "sampleClip"`) has no hostname,
credentials, or live stream -- just a `sampleClipPath`, the uploaded file
copied into that camera's own `~/pic-vision-recordings/<camera>/` folder
(so the original, wherever the operator picked it from, can be moved or
deleted afterward without breaking anything). It plugs into the existing
UI with minimal special-casing:

- **Recording control** is hidden (nothing to start/stop); a small info
  line explains why.
- **`capture.js`'s `listRecordings`** returns the one uploaded file as a
  single synthetic "recording" entry, so the existing "Send to cloud" row
  and `pipeline.js` work unchanged -- `pipeline.js` gained one thing:
  a `videoPath` override so it can skip `concatSegments` (there are no
  segments) and hand the file straight to `run_desktop_job.py`.
- **Calibration** grabs its snapshot by seeking into the file
  (`capture.js`'s new `probeDuration`/`grabFrameFromFile`, `ffmpeg -ss`)
  instead of pulling a live RTSP frame, defaulting to 10% into the clip
  (same heuristic `webapp/app.py`'s own frame-grab uses, so an intro/black
  frame at t=0 isn't what gets clicked) -- with a "frame at __ seconds /
  Reload frame" control in the modal to pick a clearer moment.
- `testConnection` for a sample clip just confirms the file still exists
  (nothing to actually connect to); the camera-grid status polling
  (`CamerasPage.jsx`) was switched from keying by hostname to keying by
  camera id in the same change, since a sample-clip camera has no
  hostname and two of them would otherwise collide on `undefined`.

**Verified:** `listRecordings`, `probeDuration`, and `grabFrameFromFile`
against a real (synthetic, `ffmpeg -f lavfi testsrc`, not footage of
anyone or anywhere real) test video -- correct duration, correct frame at
an arbitrary seek point, and a correct, informative failure when seeking
past the end of the file. `addCameraFromSampleClip` itself (the
electron-store-backed persistence) wasn't exercised the same way --
`electron-store` needs a real Electron environment to construct
(`Conf`'s `projectName` requirement), which a bare Node script run for
this verification doesn't provide -- so that path is reviewed, not
runtime-tested, pending the operator trying it in the real app.

**A related real gap found and fixed the same day:** verifying this
surfaced a leftover live-camera snapshot file in `/tmp` -- from Court 1,
the real camera this session's earlier calibration work had already
caused an incident with. Its calibration modal had evidently been closed
(app restarted or navigated away from) without Save or Cancel running,
so nothing ever called `discardSnapshot`. Fixed two ways: `capture.js`
now tracks every outstanding snapshot file and sweeps them up from
`main.js`'s `before-quit` (alongside the existing `stopAllRecordings`),
and `CalibrationModal` itself now discards its current snapshot on
unmount (e.g. navigating to a different camera's page), not only via its
own Save/Cancel buttons. Neither path corrupts anything by discarding a
file that's already gone (both Save and Cancel already remove it; the new
cleanup is a no-op in that case).

**Another real bug found trying this feature, not while building it:**
operator report -- "when i click choose file, nothing happened." Same root
cause as the `calibrationAPI` incident earlier in this file: a
`main.js`/`preload.cjs` change (`pickVideoFile`) hadn't taken effect yet
(a full app restart is needed for those, not Vite's renderer hot-reload),
so `window.systemAPI.pickVideoFile` was undefined -- but unlike the
calibration snapshot flow, `ManualAddDialog`'s `pickClipFile` had no
try/catch, so the thrown error became an unhandled promise rejection with
literally nothing visible happening. Fixed by wrapping the call, with an
explicit `typeof ... !== "function"` check that names the actual cause
("this feature isn't loaded yet -- restart the app") rather than a
generic error. Found and fixed the identical gap in `CalibrationControl`'s
"Import file…" button proactively at the same time -- same missing
try/catch, same silent-failure shape, not yet reported but clearly the
same bug class.

## Camera scanning is manual only (2026-09-03)

Operator: "dont automatically scan everytime i start the app."
`CamerasPage.jsx` used to call `startScan()` unconditionally on mount
(see "What's real vs. illustrative" above); removed outright --
scanning now only ever runs from an explicit "Scan"/"Scan again" click.
Already-configured cameras still load immediately regardless (the
separate `active`-keyed effect that reads the local camera store, kept
as-is), so this doesn't blank the page for anyone with cameras already
added -- only the automatic *network scan* for new/undiscovered ones was
removed. The empty-state copy ("picvision looks for cameras on your
Wi-Fi network automatically...") described the old behavior and no
longer matched reality, so it was reworded to describe scanning as
something the operator triggers.

## Cloud console camera sync now reports more fields (2026-09-03)

`electron/cloud.js`'s heartbeat (`cameraStatuses()`) originally sent only
`label`/`connectionType`/`manufacturer`/`model`/`status`, because that's
all any real per-camera state the cloud console had a use for. The
console's Cameras page (`pic-vision-cloud-console/app/(app)/cameras/`)
grew a click-to-open detail sheet the same day, and the operator asked
what else the desktop side already knows that could go in it. Answer: a
few real fields that were sitting in `cameras/store.js`/`capture.js`
unsent -- `firmwareVersion`/`serialNumber`/`addedAt` (from the camera's
own ONVIF `getDeviceInformation()` + when it was added), `isRecording`
(`capture.js`'s `isRecording(cameraId)`), `isCalibrated` (a boolean
derived from whether `calibPath` is set -- not the path itself), and
`recordingCount`/`lastRecordingAt` (from `listRecordings(camera)`, the
newest session's directory-name timestamp parsed back to ISO). The
privacy boundary from ADR-071/the sample-clip incident is unchanged:
`hostname`/`port`/`username`/`password`/`streamUri` still never leave
this machine, and the raw `calibPath`/`sampleClipPath` filesystem paths
(which can embed the OS username) stay local too -- only derived
booleans/counts cross for those. **Requires restarting the desktop app**
to pick up the `cloud.js` change (a main-process module, same as every
other main-process edit this project has hit before). Migration applied
directly via Supabase MCP (`cameras_add_heartbeat_detail_fields`, adds
`firmware_version`/`serial_number`/`added_at`/`is_recording`/
`is_calibrated`/`recording_count`/`last_recording_at` to `public.cameras`,
all nullable/defaulted so existing rows aren't broken); verified via a
throwaway agent + direct heartbeat POST (test data deleted after,
confirmed the real account's 3 cameras/2 agents were untouched).

## Known gaps (not built)

- RTSP-over-wifi reliability: `DECISIONS.md` ADR-030/032 found real frame
  drops/non-monotonic timestamps pulling RTSP over wifi. Recording now
  exists (`electron/capture.js`, above) and takes the same real risk on
  every session -- 10-minute segmentation bounds the damage, per that
  ADR's own conclusion, but nothing here retries a dropped connection or
  alerts if one segment comes back short.
- No packaging/signing configured beyond the bare `electron-builder`
  target list in `package.json`.
- Court calibration's flow (`electron/calibration.js`, 2026-09-03) has its
  homography math verified (reproduces a real prior calibration's exact
  RMSE) and its snapshot mechanisms verified for both sources (a real
  camera's live stream, and seeking into an uploaded sample clip), but the
  click-collection modal itself has never been exercised end-to-end
  against a real snapshot of an actual court -- neither camera on this
  machine is currently pointed at one. The sample-clip source (above)
  removes the reason that couldn't be tested safely; it just hasn't been
  clicked through in the running app yet.
- `PIC-67`'s CFR-encode NVIDIA-only gap is still open, but it's no longer
  the local agent's own problem to solve -- `pipeline.js` hands the whole
  job to `run_desktop_job.py`, which is the existing Python doing the
  encoding, same as the Flask dashboard's local-GPU route always has.
- The cloud pipeline trigger (`PIC-68`, above) has not been run
  end-to-end against real R2/RunPod resources from the desktop client --
  only the local, no-cost failure path (missing calibration) has been
  verified live. Per-venue scoped cloud credentials (`PIC-71`) are also
  still a hard prerequisite before this can point at anything but the
  operator's own `.env`.
- The Schedule page's on/off toggle still has no real effect -- capture
  now exists, but nothing reads a camera's booked sessions to
  automatically start/stop it yet (`PIC-72`). See Linear `PIC-66`/`PIC-68`
  (Done), `PIC-72`, and `PIC-73` (`Venue Deployment`) for the remaining
  integration scope.
