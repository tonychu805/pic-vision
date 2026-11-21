// The camera's own built-in web page (its admin settings: turning on ONVIF
// or RTSP, the password, resolution, the sub-stream), opened in the
// computer's browser from the add form and the camera's page (operator,
// 2026-11-21).
//
// Only a private-network address is ever opened, and only as plain
// http://<address>/ built here: the renderer passes an address the operator
// typed or a scan found, and a renderer bug or injected text must not be
// able to send the browser to an arbitrary site.
const PRIVATE_IPV4 = [
  [10, 0, 0, 0, 8],
  [172, 16, 0, 0, 12],
  [192, 168, 0, 0, 16],
  [169, 254, 0, 0, 16],
];

function ipv4(host) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  return parts.every((p) => p <= 255) ? parts : null;
}

function isPrivate(parts) {
  const n = ((parts[0] << 24) >>> 0) + (parts[1] << 16) + (parts[2] << 8) + parts[3];
  return PRIVATE_IPV4.some(([a, b, c, d, bits]) => {
    const base = ((a << 24) >>> 0) + (b << 16) + (c << 8) + d;
    const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
    return ((n & mask) >>> 0) === ((base & mask) >>> 0);
  });
}

/** http://<address>/ for a camera on the local network, or null for anything else. */
export function cameraWebPageUrl(host) {
  const h = typeof host === "string" ? host.trim() : "";
  const parts = ipv4(h);
  if (parts && isPrivate(parts)) return `http://${parts.join(".")}/`;
  if (/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.local$/i.test(h)) return `http://${h.toLowerCase()}/`;
  return null;
}
