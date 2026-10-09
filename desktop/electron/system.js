// Real local-network info for the sidebar's "Network" panel -- cheap to get
// honestly (os.networkInterfaces()), so there's no reason to hardcode a
// fake subnet the way the mockup's static prototype data does.
import { dialog, shell } from "electron";
import os from "node:os";

export function guessCidr(ip, netmask) {
  // netmask -> prefix length (only handles the common contiguous-mask case,
  // which covers every real home/venue subnet this is meant to show).
  const bits = netmask.split(".").reduce((acc, octet) => acc + Number(octet).toString(2).split("1").length - 1, 0);
  const networkOctets = ip.split(".").map((o, i) => {
    const maskOctet = Number(netmask.split(".")[i]);
    return Number(o) & maskOctet;
  });
  return `${networkOctets.join(".")}/${bits}`;
}

// VPNs, containers and hypervisors expose perfectly ordinary IPv4
// interfaces to Node, but they are not a venue LAN. Scanning them wastes
// time and, worse, leaves a real second Ethernet/Wi-Fi venue network out
// simply because Docker happened to be returned first. Keep this deliberately
// name-based and conservative: unfamiliar adapters are scanned; only common
// virtual-adapter names are excluded.
function isVirtualInterface(name) {
  return /^(lo|docker\d*|br-|veth|virbr|zt|tailscale|utun|tun\d*|tap\d*|wg\d*|vmnet|vboxnet|vEthernet)/i.test(name);
}

/**
 * Distinct directly-attached IPv4 LANs, with every local address that lives
 * on each one. Exported separately so the selection rule is testable without
 * substituting the operating system's real network interfaces.
 */
export function localNetworks(interfaces) {
  const byCidr = new Map();
  for (const [name, addrs] of Object.entries(interfaces)) {
    if (isVirtualInterface(name)) continue;
    for (const addr of addrs ?? []) {
      if (addr.family !== "IPv4" || addr.internal || !addr.address || !addr.netmask) continue;
      const cidr = guessCidr(addr.address, addr.netmask);
      const existing = byCidr.get(cidr);
      if (existing) {
        existing.interfaceNames.push(name);
        existing.addresses.push(addr.address);
      } else {
        byCidr.set(cidr, { cidr, interfaceNames: [name], addresses: [addr.address] });
      }
    }
  }
  return [...byCidr.values()];
}

export function getNetworkInfo() {
  const networks = localNetworks(os.networkInterfaces());
  // cidr/interfaceName/address remain for the sidebar and older renderer
  // code. New callers must use `networks`: a venue can have Wi-Fi and wired
  // camera LANs at once, and neither deserves to be silently ignored.
  const primary = networks[0] ?? null;
  return {
    cidr: primary?.cidr ?? null,
    interfaceName: primary?.interfaceNames[0] ?? null,
    address: primary?.addresses[0] ?? null,
    networks,
  };
}


// Native file picker for a "sample clip" camera (2026-09-03) -- a local
// video file uploaded to stand in for a live camera, so calibration and
// the cloud pipeline can be tested without one. store.js's
// addCameraFromSampleClip does the actual copy/validation; this only asks
// the OS for a path.
export async function pickVideoFile() {
  const result = await dialog.showOpenDialog({
    title: "Select a sample video clip",
    properties: ["openFile"],
    filters: [{ name: "Video", extensions: ["mp4", "mov", "mkv", "avi"] }],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
}


// Opens a link in the operator's real browser (the cloud console, from
// the "Recording and calibration live in the cloud console" pointer on
// the camera detail page). Restricted to http/https on purpose: this is
// reachable from the renderer, and shell.openExternal will happily hand
// the OS a file:// path or a custom scheme registered by some other
// installed application, which is a much larger surface than "open a web
// page" needs. Anything else is refused rather than silently ignored, so
// a caller passing the wrong thing finds out.
export async function openExternal(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`Not a valid URL: ${url}`);
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(`Refusing to open a ${parsed.protocol} link`);
  }
  await shell.openExternal(parsed.href);
}
