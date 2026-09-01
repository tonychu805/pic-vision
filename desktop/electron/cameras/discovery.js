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
// responder's actual declared type.
//
// Regex, not an XML parser, because the shape is fixed and small (one
// `<...Types>...</...Types>` element in a known SOAP envelope) and `onvif`
// itself already parsed+validated the envelope before emitting this event.
// Now verified against a real ONVIF camera's response too (a TP-Link Tapo
// C200, 2026-09-01): its `<wsdd:Types>tdn:NetworkVideoTransmitter</wsdd:Types>`
// matches correctly and is included, alongside real Scopes confirming it
// (`onvif://www.onvif.org/hardware/C200`).
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
  // Confirmed devices are accumulated directly from `device` events, not
  // by cross-referencing Discovery.probe()'s resolved list afterward --
  // that cross-reference was a real bug (found 2026-09-01, once a real
  // camera finally responded alongside the NAS boxes during testing):
  // `cam.urn` is `undefined` on this version of `onvif`'s Cam objects at
  // both the event and the resolved-list stage, so the old
  // `confirmedUrns.has(cam.urn)` filter degenerated into "does any
  // confirmed device exist at all" -- as soon as one real camera passed
  // the type check, `confirmedUrns` held `{undefined}`, which then
  // matched *every* resolved device's equally-undefined `.urn`, silently
  // re-admitting the NAS boxes the filter was supposed to reject. It
  // "worked" in earlier testing purely because no real camera had ever
  // answered a scan yet, so `confirmedUrns` stayed empty and nothing
  // could pass. Building the list straight from the event's own `cam`
  // object (same shape as the resolved one, confirmed by hostname/
  // xaddrs being populated at event time) has no cross-referencing step
  // to break.
  // Keyed by hostname, not pushed to an array -- a single physical device
  // commonly answers a WS-Discovery multicast probe more than once (over
  // multiple network interfaces, or the probe itself going out more than
  // once), each answer firing its own `device` event. Confirmed on real
  // hardware 2026-09-01: the same Tapo C200 showed up twice in one scan
  // once events were the only source of truth here (the promise-resolved
  // `Discovery.probe()` list this replaced likely deduplicated
  // internally before resolving; going straight to events lost that for
  // free). `cam.hostname` is reliably populated (confirmed via the same
  // debug logging that found the urn bug above) and is what a real
  // camera's XAddr actually identifies it by, so it's the natural key.
  const confirmed = new Map();
  const sourceIpByHostname = new Map();

  const onDevice = (cam, rinfo, xml) => {
    if (declaresNetworkVideoTransmitter(xml)) {
      confirmed.set(cam.hostname, cam);
      sourceIpByHostname.set(cam.hostname, rinfo.address);
    }
  };
  const onError = () => {}; // required per onvif's own docs -- a bad-XML reply
                            // would otherwise be an unhandled 'error' emit
  Discovery.on("device", onDevice);
  Discovery.on("error", onError);

  try {
    await Discovery.probe({ timeout }); // resolved value unused -- only
                                         // awaited for completion/timeout
    const devices = [...confirmed.values()].map(toPlainDevice);
    // cam.hostname comes from the device's own XAddr URL, which some
    // responders (e.g. the two NAS boxes this filter rejects) give as a
    // symbolic hostname rather than an IP -- ARP only indexes IPs.
    // rinfo.address is the literal UDP packet's source address, always a
    // real IP, so it's used for the vendor lookup instead of trusting
    // cam.hostname to be one. Real ONVIF cameras almost always report a
    // plain IP XAddr anyway, but this doesn't depend on that being true.
    const sourceIps = devices.map((d) => sourceIpByHostname.get(d.hostname)).filter(Boolean);
    const vendors = vendorsForIps(sourceIps);
    return devices.map((d) => ({ ...d, vendor: vendors[sourceIpByHostname.get(d.hostname)] ?? null }));
  } finally {
    Discovery.off("device", onDevice);
    Discovery.off("error", onError);
  }
}
