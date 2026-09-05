// Network/port sweep: the discovery method that doesn't depend on the
// device cooperating. WS-Discovery (discovery.js) only finds cameras that
// choose to answer its multicast probe -- a real Synology BC510 on this
// network never did (2026-09-01, progress/09.01), and was only found by
// hand: TCP-probing candidate ports and noticing RTSP (554) was open while
// neither of the two real NAS boxes on the same network had it open at
// all. This automates exactly that check across the whole subnet instead
// of one IP at a time by hand.
//
// RTSP is the only protocol checked, deliberately -- it's what actually
// separated the real camera from the two NAS false-positives in the case
// that motivated this file, and it's a real protocol standard (any RTSP
// camera, any vendor), not a vendor-specific fingerprint. HTTP-banner
// fingerprinting (the DSM/webman-redirect vs. minimal-embedded-UI
// distinction also used by hand that day) is a plausible second signal but
// unverified as a general rule across other camera/NAS vendors -- not
// added without broader evidence than one real case.
//
// Two confidence levels, not one -- a bare TCP connect only proves *some*
// service is listening on 554, not that it's actually speaking RTSP (any
// other service could be squatting on the port). `confirmed: true` means
// an RTSP OPTIONS handshake actually completed -- OPTIONS is defined by
// the RTSP spec (RFC 2326 §10.1) to require no credentials, so this is a
// real protocol-level check, not a guess, and it doesn't touch anything
// vendor-specific.
import net from "node:net";
import { vendorsForIps } from "./vendorLookup.js";

const DEFAULT_PORTS = [554];
const DEFAULT_TIMEOUT_MS = 400;
const RTSP_HANDSHAKE_TIMEOUT_MS = 300;
const DEFAULT_CONCURRENCY = 48;
export const MAX_HOSTS = 512; // safety cap -- refuses to sweep something absurd
                               // like a misdetected /8 rather than hang for
                               // ages. Exported so scanSettings.js can reject
                               // a too-big range when it's added, not only
                               // when a scan actually tries to run it.

function ipToInt(ip) {
  return ip.split(".").reduce((acc, octet) => acc * 256 + Number(octet), 0);
}
function intToIp(int) {
  return [24, 16, 8, 0].map((shift) => (int >> shift) & 255).join(".");
}

// Host IPs in a CIDR block, excluding the network and broadcast addresses
// (the standard convention for what's actually assignable).
export function hostsInCidr(cidr) {
  const [base, prefixStr] = cidr.split("/");
  const prefix = Number(prefixStr);
  const baseInt = ipToInt(base);
  const hostBits = 32 - prefix;
  const size = 2 ** hostBits;
  if (size <= 2) return []; // /31, /32 -- no usable host range
  const network = baseInt & (~0 << hostBits);
  const hosts = [];
  for (let i = 1; i < size - 1; i++) hosts.push(intToIp(network + i));
  return hosts;
}

// Opens the TCP connection, then -- if that succeeds -- sends a real RTSP
// OPTIONS request and checks for a genuine RTSP status line in the reply.
// Returns { open, confirmed }: `open` on a bare TCP accept (the old
// signal), `confirmed` only if it actually talked RTSP back.
function probeRtsp(host, port, connectTimeoutMs, handshakeTimeoutMs) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let open = false;
    let done = false;
    let buffer = "";

    const finish = (confirmed) => {
      if (done) return;
      done = true;
      socket.destroy();
      resolve({ open, confirmed });
    };

    socket.setTimeout(connectTimeoutMs);
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));

    socket.once("connect", () => {
      open = true;
      socket.setTimeout(handshakeTimeoutMs);
      const request = `OPTIONS rtsp://${host}:${port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: pic-vision-desktop\r\n\r\n`;
      socket.write(request);
    });

    socket.on("data", (chunk) => {
      buffer += chunk.toString("latin1");
      // A full status line is enough to confirm -- no need to wait for the
      // whole response (which ends in a blank line we may never see if the
      // server keeps the connection open).
      if (/^RTSP\/\d/.test(buffer)) finish(true);
    });

    socket.connect(port, host);
  });
}

async function runPool(items, concurrency, worker) {
  const results = [];
  let i = 0;
  async function next() {
    while (i < items.length) {
      const idx = i++;
      results[idx] = await worker(items[idx], idx);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, next));
  return results;
}

export async function sweepNetwork({
  cidr,
  ports = DEFAULT_PORTS,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  handshakeTimeoutMs = RTSP_HANDSHAKE_TIMEOUT_MS,
  concurrency = DEFAULT_CONCURRENCY,
  excludeHost = null,
} = {}) {
  if (!cidr) throw new Error("sweepNetwork requires a cidr (e.g. from system:networkInfo)");
  let hosts = hostsInCidr(cidr);
  if (excludeHost) hosts = hosts.filter((h) => h !== excludeHost);
  if (hosts.length > MAX_HOSTS) {
    throw new Error(`Refusing to sweep ${hosts.length} addresses (cap is ${MAX_HOSTS}) -- ${cidr} is bigger than a normal venue LAN`);
  }

  const hits = await runPool(hosts, concurrency, async (host) => {
    for (const port of ports) {
      const { open, confirmed } = await probeRtsp(host, port, timeoutMs, handshakeTimeoutMs);
      if (open) {
        return {
          hostname: host,
          port,
          confirmed,
          signal: confirmed ? `rtsp-confirmed:${port}` : `port-open:${port}`,
        };
      }
    }
    return null;
  });

  const found = hits.filter(Boolean);
  const vendors = vendorsForIps(found.map((h) => h.hostname));
  return found.map((h) => ({ ...h, vendor: vendors[h.hostname] ?? null }));
}
