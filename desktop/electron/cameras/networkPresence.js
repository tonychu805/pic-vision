// Why a scan came up empty -- the difference between "there are no cameras
// here" and "this network won't let you see them".
//
// Written 2026-09-19 after a venue visit where the operator was on the
// venue's guest Wi-Fi, found nothing, and had no way to tell which of four
// completely different situations they were in: no cameras, cameras on a
// different subnet, a network that isolates its clients, or a cloud camera
// whose RTSP was never switched on. Every one of those rendered as the
// same dead end -- "Nothing found on this network" (CamerasPage.jsx) --
// and only one of them is something the operator can fix alone.
//
// NOTHING HERE PROBES ANYONE'S DEVICES. That's the whole design
// constraint, and it's what makes this safe to run on a network we don't
// own. The three signals are:
//
//   - the OS's own ARP table (vendorLookup.js already reads it), which the
//     sweep that just ran has necessarily populated with anything that
//     answered at layer 2. Reading our own kernel's neighbour cache is not
//     a probe.
//   - SSDP M-SEARCH responders (ssdp.js), a multicast question every scan
//     already asks. Not a new behaviour, just a count that was previously
//     thrown away.
//   - mDNS peers, listened for passively: we join the group and read what
//     devices volunteer, and never transmit.
//
// The load-bearing one is ARP. Under client isolation the access point
// still forwards to the gateway but drops client-to-client frames, so ARP
// for every other host goes unanswered and the neighbour cache ends up
// holding the router and nothing else -- even though we just asked about
// all 254 addresses. That signature is what this file recognises.
import dgram from "node:dgram";
import { neighborIps } from "./vendorLookup.js";
import { hostCount, ipInCidr } from "./networkSweep.js";
import { probeSsdp } from "./ssdp.js";

const MDNS_ADDR = "224.0.0.251";
const MDNS_PORT = 5353;
const DEFAULT_LISTEN_MS = 3000;

// At or below this many neighbours in our own subnet, after a sweep has
// touched every address on it, we call the network isolated. 1 is the
// router: isolation blocks client-to-client, not client-to-gateway, so
// the gateway is exactly the entry that survives.
//
// Deliberately not higher. A wrong "isolated" verdict sends the operator
// to argue with a venue owner about their network configuration, which is
// a much worse failure than falling through to the vaguer "devices here,
// none of them a camera" -- so the threshold errs toward not claiming it.
export const ISOLATION_MAX_NEIGHBORS = 1;

/**
 * Distinct hosts heard announcing themselves over mDNS, passively.
 *
 * A SUPPORTING SIGNAL, never a deciding one. Measured 2026-09-19 on a
 * real LAN with 11 live devices: one 3-second window heard 2 peers and the
 * next heard none. mDNS is bursty, so silence over a few seconds is not
 * evidence of an empty network -- which is why verdictFor() only ever lets
 * this signal argue AGAINST isolation (any peer heard rules it out) and
 * never for it.
 *
 * `supported: false` means we never got to listen at all -- most often
 * because something else already holds 5353 (macOS runs mDNSResponder,
 * and whether a second binding is allowed varies by OS and build). That
 * is reported rather than counted as silence: "heard nothing" and "never
 * listened" are different facts, and only the first is evidence.
 */
export function listenForMdnsPeers({ listenMs = DEFAULT_LISTEN_MS, excludeAddress = null } = {}) {
  return new Promise((resolve) => {
    const peers = new Set();
    let socket;
    let settled = false;

    const finish = (supported) => {
      if (settled) return;
      settled = true;
      try { socket?.close(); } catch { /* already closed, or never opened */ }
      resolve({ supported, peers: peers.size });
    };

    try {
      socket = dgram.createSocket({ type: "udp4", reuseAddr: true });
    } catch {
      return finish(false);
    }

    // Covers a bind failure (port in use) as well as anything later. Never
    // throws into the caller: this is one of three signals and the verdict
    // degrades honestly without it.
    socket.on("error", () => finish(false));
    socket.on("message", (_message, rinfo) => {
      if (rinfo?.address && rinfo.address !== excludeAddress) peers.add(rinfo.address);
    });

    socket.bind(MDNS_PORT, () => {
      try {
        socket.addMembership(MDNS_ADDR);
      } catch {
        return finish(false); // no multicast route on this interface
      }
      setTimeout(() => finish(true), listenMs);
    });
  });
}

/**
 * How many hosts in our own subnet the OS currently has a real MAC for,
 * not counting ourselves.
 *
 * Filtered to the subnet on purpose: a dev machine's ARP table also holds
 * docker bridges and other interfaces, and counting those as "devices on
 * the venue's network" would mask exactly the signal we're looking for.
 */
export function countSubnetNeighbors(cidr, ownAddress) {
  if (!cidr) return 0;
  return neighborIps().filter((ip) => ip !== ownAddress && ipInCidr(ip, cidr)).length;
}

/**
 * The verdict, as a state chosen by WHAT THE OPERATOR SHOULD DO -- the
 * same rule probeResult.js follows, for the same reason: two situations
 * with different causes but one remedy belong in one bucket.
 *
 *   off-network  no usable network at all -- join one first
 *   isolated     the network hides its devices -- no app setting fixes
 *                this, you need to be on a different network
 *   no-cameras   devices are visible, none answered as a camera -- the
 *                camera is elsewhere, or its streaming was never enabled
 *   unknown      the signals don't support saying anything, so we don't
 *
 * Pure, with every signal injected, so it's testable under plain
 * `node --test` without sockets or an ARP table (the constraint
 * probeResult.js and frameRate.js already carry).
 */
export function verdictFor({ cidr, neighbors = 0, ssdpResponders = 0, mdns = null }) {
  const facts = {
    cidr,
    addressesChecked: cidr ? hostCount(cidr) : 0,
    neighbors,
    ssdpResponders,
    mdnsPeers: mdns?.supported ? mdns.peers : null,
  };

  if (!cidr) {
    return {
      state: "off-network",
      title: "Not connected to a network",
      detail:
        "This computer isn't on a network right now, so there was nothing to search. " +
        "Join the venue's Wi-Fi and scan again.",
      facts,
    };
  }

  // An mDNS listen that never got off the ground contributes nothing --
  // counting its zero as silence would manufacture evidence.
  const mdnsPeers = mdns?.supported ? mdns.peers : 0;
  const anyPeerSeen = neighbors > ISOLATION_MAX_NEIGHBORS || ssdpResponders > 0 || mdnsPeers > 0;

  if (!anyPeerSeen) {
    const nothingAtAll = neighbors === 0
      ? "no other device on it is visible from here at all"
      : "the only thing visible from here is the router itself";
    return {
      state: "isolated",
      title: "This network keeps devices apart",
      detail:
        `You're on ${cidr}, and after checking every address on it, ${nothingAtAll} — ` +
        "no camera, and no device of any other kind either. That's how guest Wi-Fi is " +
        "normally set up, and nothing in picvision can get around it. " +
        "Ask the venue to put this computer on the same network as their cameras — " +
        "their main or camera network, not the guest one.",
      facts,
    };
  }

  return {
    state: "no-cameras",
    title: "Devices here, but none of them a camera",
    detail:
      `You're on ${cidr}, and ${describeCount(neighbors, ssdpResponders, mdnsPeers)} — ` +
      "but nothing answered as a camera. Either the cameras are on a different network, " +
      "or their streaming hasn't been switched on: most cloud cameras keep it off until " +
      "the owner turns it on in the camera's own app. If you know the camera's address, " +
      "you can add it by hand.",
    facts,
  };
}

// The neighbour count includes the router, so it's described rather than
// presented as a bare device count that would be off by one.
function describeCount(neighbors, ssdpResponders, mdnsPeers) {
  if (neighbors > 0) {
    return neighbors === 1
      ? "the only thing visible from here is the router"
      : `${neighbors} other devices are visible from here (the router among them)`;
  }
  // Nothing in the neighbour cache, but something answered a multicast
  // question -- so a count of announcers is all we can honestly give.
  const announced = Math.max(ssdpResponders, mdnsPeers);
  return announced === 1
    ? "one other device announced itself"
    : `${announced} other devices announced themselves`;
}

/**
 * Run the three checks and return the verdict. Called only when a scan
 * that actually completed found nothing, so the few seconds it spends
 * cost nothing on the normal path -- and are spent at the one moment the
 * operator is stuck and has nothing else to look at.
 */
export async function explainEmptyScan({ cidr, address, listenMs = DEFAULT_LISTEN_MS } = {}) {
  // Both are fixed listening windows, so they run together rather than
  // back to back (the same reasoning main.js's scan already applies to
  // probeSsdp alongside the port sweep).
  const [mdns, responders] = await Promise.all([
    listenForMdnsPeers({ listenMs, excludeAddress: address }),
    probeSsdp({ timeoutMs: listenMs }),
  ]);
  // Read last: the sweep that just ran is what populated the neighbour
  // cache, and entries age out, so later is better than earlier.
  const neighbors = countSubnetNeighbors(cidr, address);
  return verdictFor({ cidr, neighbors, ssdpResponders: responders.size, mdns });
}
