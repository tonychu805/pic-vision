// Derives the mockup's card/detail view-model (STATE_META, card(), sel())
// from real data: configured cameras (cameraAPI.list()/add()), transient
// discovery results (cameraAPI.discover()), and per-camera live-test status
// (cameraAPI.testConnection()) -- unlike the mockup's static DEVICES
// sample, every field here traces to a real call or is explicitly "Not
// available" rather than invented (ONVIF's GetDeviceInformation has no
// MAC address field, so that one's always "Not available", never guessed).

// The status dot each of these used to carry is gone (2026-09-06): it sat
// next to the tag saying the same thing twice, and three of the six
// states drew it in near-identical greys (neutral-600/500/400), so it
// added noise rather than a second reading of the state. The tag now
// carries a semantic colour instead of every non-ok state being the same
// neutral chip.
//
// "Online", not "Streaming" (2026-09-06): all this state means is that
// testConnection reached the camera. Nothing is being streamed or
// recorded -- recording is started from the cloud console -- and
// "Streaming" invited a venue owner to believe footage was being captured.
export const STATE_META = {
  ok: { label: "Online", tagClass: "tag tag-success" },
  checking: { label: "Checking…", tagClass: "tag tag-neutral" },
  offline: { label: "Not answering", tagClass: "tag tag-danger" },
  auth: { label: "Sign-in needed", tagClass: "tag tag-warning" },
  // Two sweep-hit levels, distinct from `auth` (which means "we know this
  // is ONVIF, just needs credentials"): `rtsp` means an actual RTSP
  // OPTIONS handshake completed (RFC 2326 -- needs no credentials, so this
  // is a real protocol-level confirmation, not a guess) -- something is
  // definitely speaking RTSP, ONVIF support is still unknown. `unconfirmed`
  // is weaker still: the TCP port answered but nothing recognizable as
  // RTSP came back, so this could be any service, camera or not.
  rtsp: { label: "Ready to add", tagClass: "tag tag-outline" },
  unconfirmed: { label: "Unconfirmed", tagClass: "tag tag-neutral" },
};

// Builds a full card for one configured (persisted) camera -- the only
// place this shape is assembled, so a card handed to cardVisuals()/JSX
// always has every field STATE_META and the detail page expect. A card
// missing `state` (or any of these) isn't just visually incomplete --
// cardVisuals() does `STATE_META[card.state].label` with no fallback, so
// a card built any other way throws and takes down the whole render tree
// (found 2026-09-01: the post-sign-in flow in App.jsx built one of these
// by hand, missing every field but `key`/`kind`/`camera`, and crashed the
// app the moment a real ONVIF sign-in actually succeeded for the first
// time this session -- the underlying `cameraAPI.add()` call had already
// completed and saved the camera, so it looked like "sign in failed" when
// the save had actually worked and only the *next* render crashed).
export function configuredCard(c, state) {
  const isSampleClip = c.connectionType === "sampleClip";
  return {
    key: c.id,
    kind: "configured",
    camera: c,
    name: c.label,
    // A sample-clip camera has no network address -- nothing to show here.
    ip: isSampleClip ? null : c.hostname,
    subtitle: isSampleClip
      ? "Sample clip"
      : [c.manufacturer, c.model].filter(Boolean).join(" ") || (c.connectionType === "rtsp" ? "Camera" : "ONVIF camera"),
    state,
  };
}

// A "card" is either a configured (persisted) camera, an ONVIF discovery
// result not yet signed in to, or a network-sweep hit (RTSP port open,
// ONVIF unconfirmed) -- unified so the grid can render all three the same
// way the mockup's DEVICES list does (some entries already streaming, some
// needing auth).
export function buildCards({ configured, discovered, sweepHits, statusById }) {
  // .filter(Boolean): a sample-clip camera has no hostname, and several
  // configured ones sharing `undefined` here must never be treated as the
  // same discovered/sweep device.
  const configuredHostnames = new Set(configured.map((c) => c.hostname).filter(Boolean));

  // Keyed by id, not hostname -- a sample-clip camera has no hostname at
  // all, and two of them would otherwise collide under the same
  // `undefined` key and show each other's status.
  const configuredCards = configured.map((c) => configuredCard(c, statusById[c.id] ?? "checking"));

  // Plain-language names for anything not yet added -- a venue owner has
  // no use for a raw IP or protocol name as the headline. Vendor (from
  // vendorLookup.js's MAC lookup, generic across brands) is included when
  // known since "which camera is this" is exactly what a first-time,
  // non-technical user needs to recognize their own device by.
  const discoveredCards = discovered
    .filter((d) => !configuredHostnames.has(d.hostname))
    .map((d) => ({
      key: d.hostname,
      kind: "discovered",
      device: d,
      name: d.vendor ? `${d.vendor} camera` : "Camera found",
      ip: `${d.hostname}:${d.port}`,
      subtitle: "Tap to sign in",
      state: "auth",
    }));

  const discoveredHostnames = new Set(discovered.map((d) => d.hostname));
  const sweepCards = (sweepHits ?? [])
    .filter((s) => !configuredHostnames.has(s.hostname) && !discoveredHostnames.has(s.hostname))
    .map((s) => ({
      key: s.hostname,
      kind: "sweep",
      device: s,
      // Confidence-appropriate wording: `confirmed` means a real RTSP
      // handshake happened -- safe to call it a camera. `unconfirmed`
      // means only that a port answered -- could be anything, so it's
      // called a "device," not a "camera," until proven otherwise.
      name: s.confirmed
        ? s.vendor
          ? `${s.vendor} camera found`
          : "Camera found"
        : s.vendor
          ? `${s.vendor} device found`
          : "Possible device found",
      ip: `${s.hostname}:${s.port}`,
      subtitle: s.confirmed ? "Tap to set up" : "Tap to check",
      state: s.confirmed ? "rtsp" : "unconfirmed",
    }));

  return [...configuredCards, ...discoveredCards, ...sweepCards];
}

export function cardVisuals(card) {
  const meta = STATE_META[card.state];
  const live = card.state === "ok";
  // "Online" reads wrong for a sample-clip camera, which has no network
  // presence at all -- STATE_META's "ok" for one of those just means "its
  // file is there," so say that instead.
  const isSampleClip = card.kind === "configured" && card.camera.connectionType === "sampleClip";
  return {
    ...card,
    stateLabel: isSampleClip && card.state === "ok" ? "File ready" : meta.label,
    stateTagClass: meta.tagClass,
    live,
    thumbIcon: live
      ? "ph ph-video-camera"
      : card.state === "rtsp"
        ? "ph ph-video-camera"
        : card.state === "unconfirmed"
          ? "ph ph-question"
          : card.state === "auth"
            ? "ph ph-lock-simple"
            : "ph ph-plugs",
  };
}

// Identity/network/streams panels for the detail page -- "Not available"
// wherever ONVIF's GetDeviceInformation genuinely has no such field, rather
// than inventing MAC/subnet/gateway values the way the mockup's fixtures do.
// What the camera says it's actually sending, read from its ONVIF profile
// when it was added or last checked (cameras/store.js's streamProfile).
// Shown because all three numbers change how well detection works and none
// of them were visible anywhere before: H.265 has silently broken decoding
// on this project's footage once already, and anything below 30fps makes the
// ball travel further between frames than the tracker was tuned for.
export function profileSpec(camera) {
  const p = camera.profile;
  if (!p) return null;
  const parts = [];
  if (p.codec) parts.push(p.codec === "H265" ? "H.265" : p.codec === "H264" ? "H.264" : p.codec);
  if (p.width && p.height) parts.push(`${p.width}x${p.height}`);
  const fps = frameRateSummary(camera);
  if (fps) parts.push(fps);
  if (p.bitrateKbps) parts.push(`${(p.bitrateKbps / 1000).toFixed(1)} Mbps`);
  return parts.length ? parts.join(" · ") : null;
}

// Three states, never two. "No warning" previously meant either "checked,
// fine" or "never managed to check" -- indistinguishable, which is the same
// silent-failure shape the frame-rate guard exists to remove, just moved up
// a level. A camera we couldn't measure says so.
export function frameRateSummary(camera) {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);
  const configured = num(camera.profile?.fps);
  const measured = num(camera.profile?.measuredFps);
  if (measured === null && configured === null) return "frame rate not determined";
  if (measured !== null && configured !== null && Math.abs(measured - configured) / configured > 0.15) {
    return `${configured} fps set, ${Math.round(measured)} arriving`;
  }
  const effective = measured ?? configured;
  return `${Math.round(effective)} fps${measured !== null ? " (measured)" : ""}`;
}

export function detailPanels(camera) {
  const na = "Not available";
  const viaRtsp = camera.connectionType === "rtsp";
  if (camera.connectionType === "sampleClip") {
    return {
      identity: [
        { k: "Source", v: "Uploaded sample clip" },
        { k: "Vendor", v: na },
        { k: "Model", v: na },
        { k: "Serial", v: na },
        { k: "Firmware", v: na },
      ],
      network: [{ k: "Address", v: na }, { k: "Mode", v: "Not networked" }],
      streams: camera.sampleClipPath
        ? [{ label: "FILE", url: camera.sampleClipPath, spec: "uploaded video file, not a live stream" }]
        : [],
    };
  }
  return {
    identity: [
      { k: "Vendor", v: camera.manufacturer || na },
      // A camera added via the RTSP fallback never went through ONVIF's
      // GetDeviceInformation -- model/serial/firmware are genuinely
      // unknown, not just unset, so this says so rather than implying
      // they were looked up and came back empty.
      { k: "Model", v: viaRtsp ? "Not available (added without ONVIF)" : camera.model || na },
      { k: "Serial", v: viaRtsp ? "Not available (added without ONVIF)" : camera.serialNumber || na },
      { k: "MAC", v: na },
      { k: "Firmware", v: viaRtsp ? "Not available (added without ONVIF)" : camera.firmwareVersion || na },
    ],
    network: [
      { k: "Address", v: `${camera.hostname}:${camera.port}` },
      {
        k: viaRtsp ? "Stream path" : "ONVIF path",
        v: camera.path || (viaRtsp ? na : "/onvif/device_service (default)"),
      },
      { k: "Mode", v: na },
      { k: "Subnet", v: na },
      { k: "Gateway", v: na },
    ],
    streams: camera.streamUri
      ? [{ label: "MAIN", url: camera.streamUri, spec: profileSpec(camera) || (viaRtsp ? "found directly, without ONVIF" : "reported by camera's GetStreamUri") }]
      : [],
  };
}
