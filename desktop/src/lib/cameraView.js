// Derives the mockup's card/detail view-model (STATE_META, card(), sel())
// from real data: configured cameras (cameraAPI.list()/add()), transient
// discovery results (cameraAPI.discover()), and per-camera live-test status
// (cameraAPI.testConnection()) -- unlike the mockup's static DEVICES
// sample, every field here traces to a real call or is explicitly "Not
// available" rather than invented (ONVIF's GetDeviceInformation has no
// MAC address field, so that one's always "Not available", never guessed).

export const STATE_META = {
  ok: { label: "Streaming", dot: "var(--color-accent-400)", tagClass: "tag tag-accent" },
  checking: { label: "Checking…", dot: "var(--color-neutral-500)", tagClass: "tag tag-neutral" },
  offline: { label: "Not answering", dot: "var(--color-neutral-600)", tagClass: "tag tag-neutral" },
  auth: { label: "Sign-in needed", dot: "var(--color-neutral-400)", tagClass: "tag tag-neutral" },
  // Two sweep-hit levels, distinct from `auth` (which means "we know this
  // is ONVIF, just needs credentials"): `rtsp` means an actual RTSP
  // OPTIONS handshake completed (RFC 2326 -- needs no credentials, so this
  // is a real protocol-level confirmation, not a guess) -- something is
  // definitely speaking RTSP, ONVIF support is still unknown. `unconfirmed`
  // is weaker still: the TCP port answered but nothing recognizable as
  // RTSP came back, so this could be any service, camera or not.
  rtsp: { label: "Ready to add", dot: "var(--color-accent-2-400)", tagClass: "tag tag-outline" },
  unconfirmed: { label: "Unconfirmed", dot: "var(--color-neutral-500)", tagClass: "tag tag-neutral" },
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
  return {
    key: c.id,
    kind: "configured",
    camera: c,
    name: c.label,
    ip: c.hostname,
    subtitle: [c.manufacturer, c.model].filter(Boolean).join(" ") || (c.connectionType === "rtsp" ? "Camera" : "ONVIF camera"),
    proto: c.connectionType === "rtsp" ? "RTSP" : "ONVIF",
    state,
  };
}

// A "card" is either a configured (persisted) camera, an ONVIF discovery
// result not yet signed in to, or a network-sweep hit (RTSP port open,
// ONVIF unconfirmed) -- unified so the grid can render all three the same
// way the mockup's DEVICES list does (some entries already streaming, some
// needing auth).
export function buildCards({ configured, discovered, sweepHits, statusByHostname }) {
  const configuredHostnames = new Set(configured.map((c) => c.hostname));

  const configuredCards = configured.map((c) => configuredCard(c, statusByHostname[c.hostname] ?? "checking"));

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
      proto: "ONVIF",
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
      proto: "RTSP",
      state: s.confirmed ? "rtsp" : "unconfirmed",
    }));

  return [...configuredCards, ...discoveredCards, ...sweepCards];
}

export function cardVisuals(card) {
  const meta = STATE_META[card.state];
  const live = card.state === "ok";
  return {
    ...card,
    stateLabel: meta.label,
    stateTagClass: meta.tagClass,
    dot: meta.dot,
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
export function detailPanels(camera) {
  const na = "Not available";
  const viaRtsp = camera.connectionType === "rtsp";
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
      ? [{ label: "MAIN", url: camera.streamUri, spec: viaRtsp ? "found directly, without ONVIF" : "reported by camera's GetStreamUri" }]
      : [],
  };
}
