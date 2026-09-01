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
  rtsp: { label: "RTSP confirmed", dot: "var(--color-accent-2-400)", tagClass: "tag tag-outline" },
  unconfirmed: { label: "Possible camera", dot: "var(--color-neutral-500)", tagClass: "tag tag-neutral" },
};

// A "card" is either a configured (persisted) camera, an ONVIF discovery
// result not yet signed in to, or a network-sweep hit (RTSP port open,
// ONVIF unconfirmed) -- unified so the grid can render all three the same
// way the mockup's DEVICES list does (some entries already streaming, some
// needing auth).
export function buildCards({ configured, discovered, sweepHits, statusByHostname }) {
  const configuredHostnames = new Set(configured.map((c) => c.hostname));

  const configuredCards = configured.map((c) => {
    const state = statusByHostname[c.hostname] ?? "checking";
    return {
      key: c.id,
      kind: "configured",
      camera: c,
      name: c.label,
      ip: c.hostname,
      subtitle: [c.manufacturer, c.model].filter(Boolean).join(" ") || "ONVIF camera",
      proto: "ONVIF",
      state,
    };
  });

  const discoveredCards = discovered
    .filter((d) => !configuredHostnames.has(d.hostname))
    .map((d) => ({
      key: d.hostname,
      kind: "discovered",
      device: d,
      name: d.hostname,
      ip: `${d.hostname}:${d.port}`,
      subtitle: d.vendor ? `${d.vendor} — unassigned camera` : "Unassigned camera",
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
      name: s.hostname,
      ip: `${s.hostname}:${s.port}`,
      subtitle: [
        s.vendor,
        s.confirmed ? `RTSP confirmed (port ${s.port})` : `port ${s.port} open, not confirmed as RTSP`,
      ]
        .filter(Boolean)
        .join(" — "),
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
  return {
    identity: [
      { k: "Vendor", v: camera.manufacturer || na },
      { k: "Model", v: camera.model || na },
      { k: "Serial", v: camera.serialNumber || na },
      { k: "MAC", v: na },
      { k: "Firmware", v: camera.firmwareVersion || na },
    ],
    network: [
      { k: "Address", v: `${camera.hostname}:${camera.port}` },
      { k: "ONVIF path", v: camera.path || "/onvif/device_service (default)" },
      { k: "Mode", v: na },
      { k: "Subnet", v: na },
      { k: "Gateway", v: na },
    ],
    streams: camera.streamUri
      ? [{ label: "MAIN", url: camera.streamUri, spec: "reported by camera's GetStreamUri" }]
      : [],
  };
}
