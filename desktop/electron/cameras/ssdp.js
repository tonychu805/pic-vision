// SSDP/UPnP discovery: what a camera tells you about itself before you
// have any credentials.
//
// Added 2026-09-09 because a scan result read "Synology camera,
// 192.168.1.121:554" and nothing more, which is no help at all when a
// venue has four identical cameras on four poles. Measured on real
// hardware, this is what the two cameras on this network volunteer:
//
//   Synology BC500  SSDP: name "pic-vision-test-001-BC500", model BC500,
//                   serial 2310VSRCJY482, deviceType IPCamera:1
//                   ONVIF WS-Discovery: never answers at all
//   TP-Link C200    SSDP: silent
//                   ONVIF: name/hardware C200, location "Hong Kong"
//
// They identify themselves over *opposite* protocols, which is the whole
// argument for this module existing alongside discovery.js rather than
// instead of it: either one alone leaves half the cameras anonymous.
//
// `deviceType` is worth more than the rest combined for classification --
// `urn:schemas-upnp-org:device:IPCamera:1` is the device declaring what it
// is, which beats inferring "camera" from an open port 554.
import dgram from "node:dgram";

const MULTICAST_ADDR = "239.255.255.250";
const MULTICAST_PORT = 1900;
const DEFAULT_PROBE_MS = 3000;
const DESCRIPTION_TIMEOUT_MS = 2500;
// A device description is a few hundred bytes. Anything wildly bigger is
// not one, and we are fetching from an unauthenticated device on a venue
// LAN, so it does not get to stream unbounded data into this process.
const MAX_DESCRIPTION_BYTES = 64 * 1024;

const SEARCH = [
  "M-SEARCH * HTTP/1.1",
  `HOST: ${MULTICAST_ADDR}:${MULTICAST_PORT}`,
  'MAN: "ssdp:discover"',
  "MX: 2",
  "ST: ssdp:all",
  "", "",
].join("\r\n");

function header(text, name) {
  return text.match(new RegExp(`^${name}:\\s*(.+)$`, "im"))?.[1]?.trim() ?? null;
}

/**
 * Who answered, and where their description lives. One UDP round, no
 * per-host requests -- those come later, and only for hosts the camera
 * scan already cares about.
 *
 * Everything on the LAN answers this (on the dev network: a Chromecast, a
 * Windows box and two NAS boxes), which is exactly why the caller filters
 * before fetching anything.
 */
export function probeSsdp({ timeoutMs = DEFAULT_PROBE_MS } = {}) {
  return new Promise((resolve) => {
    const responders = new Map();
    let socket;
    try {
      socket = dgram.createSocket({ type: "udp4", reuseAddr: true });
    } catch {
      return resolve(responders); // enrichment only -- never fail a scan over it
    }

    const finish = () => {
      try { socket.close(); } catch { /* already closed */ }
      resolve(responders);
    };

    socket.on("error", finish);
    socket.on("message", (message, rinfo) => {
      if (responders.has(rinfo.address)) return; // first answer per host is enough
      const text = message.toString("latin1");
      const location = header(text, "LOCATION");
      if (!location) return;
      responders.set(rinfo.address, { location, usn: header(text, "USN"), server: header(text, "SERVER") });
    });

    socket.bind(() => {
      try {
        socket.setBroadcast(true);
        socket.send(Buffer.from(SEARCH), MULTICAST_PORT, MULTICAST_ADDR);
      } catch {
        return finish();
      }
      setTimeout(finish, timeoutMs);
    });
  });
}

function tag(xml, name) {
  const match = xml.match(new RegExp(`<${name}>([^<]*)</${name}>`, "i"));
  const value = match?.[1]?.trim();
  return value ? value : null;
}

/** The fields worth showing a person, from a UPnP device description. */
export function parseDescription(xml) {
  return {
    deviceType: tag(xml, "deviceType"),
    friendlyName: tag(xml, "friendlyName"),
    manufacturer: tag(xml, "manufacturer"),
    model: tag(xml, "modelName"),
    modelDescription: tag(xml, "modelDescription"),
    serial: tag(xml, "serialNumber"),
    udn: tag(xml, "UDN"),
    webUi: tag(xml, "presentationURL"),
  };
}

/** Does this description say "I am a camera", rather than us guessing? */
export function declaresCamera(description) {
  return /:device:(IPCamera|Camera|DigitalSecurityCamera)/i.test(description?.deviceType ?? "");
}

async function fetchDescription(ip, location) {
  // The LOCATION comes from an unauthenticated UDP packet, so it is not
  // trusted to point anywhere it likes: only a description served by the
  // host that answered is fetched. Otherwise any device on the LAN could
  // aim this process at an arbitrary URL by answering a probe.
  let url;
  try {
    url = new URL(location);
  } catch {
    return null;
  }
  if (url.hostname !== ip || (url.protocol !== "http:" && url.protocol !== "https:")) return null;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(DESCRIPTION_TIMEOUT_MS), redirect: "error" });
    if (!res.ok) return null;
    const xml = (await res.text()).slice(0, MAX_DESCRIPTION_BYTES);
    return parseDescription(xml);
  } catch {
    return null;
  }
}

/**
 * Descriptions for the given IPs, from an already-collected responder map.
 *
 * Split from the probe so the probe can run alongside the rest of a scan
 * while the fetches wait for the scan to say which hosts matter -- a venue
 * LAN answers with printers and TVs, and none of them need an HTTP request.
 */
export async function describeSsdpHosts(responders, ips) {
  const wanted = ips.filter((ip) => responders.has(ip));
  const entries = await Promise.all(
    wanted.map(async (ip) => [ip, await fetchDescription(ip, responders.get(ip).location)]),
  );
  return Object.fromEntries(entries.filter(([, description]) => description));
}
