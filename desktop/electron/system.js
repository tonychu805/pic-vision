// Real local-network info for the sidebar's "Network" panel -- cheap to get
// honestly (os.networkInterfaces()), so there's no reason to hardcode a
// fake subnet the way the mockup's static prototype data does.
import os from "node:os";

function guessCidr(ip, netmask) {
  // netmask -> prefix length (only handles the common contiguous-mask case,
  // which covers every real home/venue subnet this is meant to show).
  const bits = netmask.split(".").reduce((acc, octet) => acc + Number(octet).toString(2).split("1").length - 1, 0);
  const networkOctets = ip.split(".").map((o, i) => {
    const maskOctet = Number(netmask.split(".")[i]);
    return Number(o) & maskOctet;
  });
  return `${networkOctets.join(".")}/${bits}`;
}

export function getNetworkInfo() {
  const interfaces = os.networkInterfaces();
  for (const [name, addrs] of Object.entries(interfaces)) {
    for (const addr of addrs ?? []) {
      if (addr.family === "IPv4" && !addr.internal) {
        return { cidr: guessCidr(addr.address, addr.netmask), interfaceName: name, address: addr.address };
      }
    }
  }
  return { cidr: null, interfaceName: null, address: null };
}
