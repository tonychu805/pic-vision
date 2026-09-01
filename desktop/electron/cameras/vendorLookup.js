// Resolves a LAN IP to its manufacturer via ARP (IP -> MAC, the OS already
// knows this for anything recently contacted, e.g. by a scan probe) + the
// IEEE OUI registry (MAC's first 3 bytes -> vendor, `oui-data` -- bundled
// locally, updated upstream every few days, no live network call and
// nothing about the venue's devices ever leaves the machine). Generic by
// construction: works the same for any vendor, not just the one this was
// built against.
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
// oui-data ships plain JSON with no exports condition for ESM `with {type:
// "json"}` assertions verified against this Electron/Node build -- CJS
// require() loads JSON natively and unambiguously (confirmed working
// directly, not assumed), same reasoning as discovery.js/store.js's onvif
// import workaround: don't guess at newer ESM interop syntax when a
// well-established CJS path already just works.
const require = createRequire(import.meta.url);
const ouiData = require("oui-data");

function normalizeMac(mac) {
  return mac.replace(/[:-]/g, "").toUpperCase();
}

// IEEE registrants are legal entities, not brand names -- "Hangzhou
// Hikvision Digital Technology Co.,Ltd." rather than "Hikvision". Trims
// generic corporate-entity suffixes so it fits a card's title line; this
// is a blanket string rule (any registrant, not a per-vendor lookup
// table), consistent with staying vendor-neutral rather than special-
// casing brands the way a curated name-mapping list would.
const CORPORATE_SUFFIX_RE =
  /,?\s*(incorporated|inc\.?|corporation|corp\.?|co\.,?\s*ltd\.?|company\s*ltd\.?|limited|ltd\.?|llc|gmbh|s\.a\.|ag|pte\.?\s*ltd\.?)\s*$/i;

function simplifyVendorName(name) {
  // No comma pre-split -- "Co.,Ltd." is one suffix spanning a comma, and
  // splitting first would sever it into an unstripped "Co." remainder.
  let simplified = name.trim();
  let prev;
  do {
    prev = simplified;
    simplified = simplified.replace(CORPORATE_SUFFIX_RE, "").trim();
  } while (simplified !== prev && simplified.length > 0);
  return simplified || name;
}

function vendorForMac(mac) {
  const key = normalizeMac(mac).slice(0, 6);
  const entry = ouiData[key];
  if (!entry) return null;
  const fullName = entry.split("\n")[0].trim(); // first line is the
                                                 // registrant; the rest is
                                                 // a mailing address, unused
  return simplifyVendorName(fullName);
}

// One-shot read of the OS's whole ARP table -- cheaper than looking up
// each IP individually, especially on macOS/Windows where that means a
// new subprocess per address instead of per scan.
function readArpTable() {
  const table = new Map();
  if (process.platform === "linux") {
    // Columns: IP, HW type, Flags, HW address, Mask, Device
    const lines = readFileSync("/proc/net/arp", "utf8").split("\n").slice(1);
    for (const line of lines) {
      const cols = line.trim().split(/\s+/);
      if (cols.length < 4) continue;
      const [ip, , , mac] = cols;
      if (mac && mac !== "00:00:00:00:00:00") table.set(ip, mac);
    }
    return table;
  }

  // macOS / Windows: `arp -a` output, one physical entry per line, e.g.
  // "? (192.168.1.121) at 90:9:d0:3b:7a:38 on en0 ..." (macOS) or
  // "  192.168.1.121         90-09-d0-3b-7a-38     dynamic" (Windows).
  const out = execFileSync("arp", ["-a"], { encoding: "utf8", timeout: 3000 });
  const ipRe = /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/;
  const macRe = /([0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2}/;
  for (const line of out.split("\n")) {
    const ipMatch = line.match(ipRe);
    const macMatch = line.match(macRe);
    if (ipMatch && macMatch) table.set(ipMatch[1], macMatch[0]);
  }
  return table;
}

// { [ip]: vendorName | null } for every ip in `ips` that's in the ARP
// table right now. Silently returns {} on any lookup failure (missing
// /proc/net/arp, no `arp` binary, permission issues) -- this is a nice-to-
// have enrichment, never load-bearing for discovery itself.
export function vendorsForIps(ips) {
  let arpTable;
  try {
    arpTable = readArpTable();
  } catch {
    return {};
  }
  const result = {};
  for (const ip of ips) {
    const mac = arpTable.get(ip);
    result[ip] = mac ? vendorForMac(mac) : null;
  }
  return result;
}
