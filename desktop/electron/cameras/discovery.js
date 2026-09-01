// ONVIF WS-Discovery: finds NVT (camera) devices on the local network.
// STRATEGY.md §5's "camera discovery/management" bullet -- new scope, no
// prior code. Discovered devices come back unconnected (no credentials
// exchanged yet); connect() in store.js is what actually talks to a camera.
// onvif's promises/index.js is CJS re-exporting via nested require() calls,
// which cjs-module-lexer can't statically detect as named exports -- import
// the module object and destructure at runtime instead.
import onvifPromises from "onvif/promises/index.js";
import { vendorsForIps } from "./vendorLookup.js";
const { Discovery } = onvifPromises;

const DEFAULT_TIMEOUT_MS = 5000;

// The `onvif` package's Discovery.probe() sends a WS-Discovery Probe scoped
// to <Types>dn:NetworkVideoTransmitter</Types>, but never checks a
// responder's own declared <wsd:Types> before treating it as a camera --
// confirmed on real hardware (2026-09-01): two Synology NAS boxes on this
// network answered the probe and were returned as "cameras" by the library,
// both self-reporting `wsd:Types = "wsdp:Device pub:Computer"` in their raw
// SOAP response (Windows-network-browsing/WSD's generic "this is a
// computer" type, unrelated to ONVIF). The library's own event API is the
// only place the raw XML is exposed (the promise-resolved Cam objects drop
// it entirely), so this listens for `device` events to filter by the
// responder's actual declared type, cross-referenced against the promise's
// resolved list for completion/timeout handling.
//
// Regex, not an XML parser, because the shape is fixed and small (one
// `<wsd:Types>...</wsd:Types>` element in a known SOAP envelope) and
// `onvif` itself already parsed+validated the envelope before emitting
// this event -- a second full XML parse here would be pure overhead for a
// pattern this constrained. NOT verified against a real ONVIF camera's
// response shape in this session (none was reachable to test) -- only
// confirmed to correctly reject the two non-camera responses above.
function declaresNetworkVideoTransmitter(xml) {
  const match = xml.match(/<[\w:]*Types>([^<]*)<\/[\w:]*Types>/i);
  if (!match) return false;
  return /NetworkVideoTransmitter/i.test(match[1]);
}

// Cam instances aren't safely IPC-serializable (internal EventEmitter state,
// circular refs) -- reduce each hit to the plain fields the renderer needs.
function toPlainDevice(cam) {
  return {
    hostname: cam.hostname,
    port: cam.port,
    path: cam.path ?? "/",
    urn: cam.urn,
    xaddrs: (cam.xaddrs ?? []).map((u) => u.toString()),
  };
}

export async function discoverCameras({ timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const confirmedUrns = new Set();
  // cam.hostname comes from the device's own XAddr URL, which some
  // responders (e.g. the two NAS boxes this filter rejects) give as a
  // symbolic hostname rather than an IP -- ARP only indexes IPs. rinfo.address
  // is the literal UDP packet's source address, always a real IP, so it's
  // used for the vendor lookup instead of trusting cam.hostname to be one.
  // Real ONVIF cameras almost always report a plain IP XAddr anyway, but
  // this doesn't depend on that being true.
  const sourceIpByUrn = new Map();

  const onDevice = (cam, rinfo, xml) => {
    if (declaresNetworkVideoTransmitter(xml)) {
      confirmedUrns.add(cam.urn);
      sourceIpByUrn.set(cam.urn, rinfo.address);
    }
  };
  const onError = () => {}; // required per onvif's own docs -- a bad-XML reply
                            // would otherwise be an unhandled 'error' emit
  Discovery.on("device", onDevice);
  Discovery.on("error", onError);

  try {
    const cams = await Discovery.probe({ timeout });
    const devices = cams.filter((cam) => confirmedUrns.has(cam.urn)).map(toPlainDevice);
    const sourceIps = devices.map((d) => sourceIpByUrn.get(d.urn)).filter(Boolean);
    const vendors = vendorsForIps(sourceIps);
    return devices.map((d) => ({ ...d, vendor: vendors[sourceIpByUrn.get(d.urn)] ?? null }));
  } finally {
    Discovery.off("device", onDevice);
    Discovery.off("error", onError);
  }
}
