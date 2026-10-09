// The camera scan used to pick the first interface Node returned. That can
// be a Wi-Fi guest LAN while cameras are wired, or a Docker bridge before a
// real NIC. These tests keep the selection rule independent of this test
// machine's own adapters.
import assert from "node:assert/strict";
import { test } from "node:test";
import { guessCidr, localNetworks } from "./system.js";

test("guessCidr preserves the interface's actual netmask", () => {
  assert.equal(guessCidr("10.17.3.9", "255.255.254.0"), "10.17.2.0/23");
  assert.equal(guessCidr("192.168.2.42", "255.255.255.0"), "192.168.2.0/24");
});

test("localNetworks includes every real local LAN, not just the first adapter", () => {
  const networks = localNetworks({
    en0: [{ family: "IPv4", internal: false, address: "192.168.2.42", netmask: "255.255.255.0" }],
    en5: [{ family: "IPv4", internal: false, address: "192.168.1.10", netmask: "255.255.255.0" }],
  });
  assert.deepEqual(networks, [
    { cidr: "192.168.2.0/24", interfaceNames: ["en0"], addresses: ["192.168.2.42"] },
    { cidr: "192.168.1.0/24", interfaceNames: ["en5"], addresses: ["192.168.1.10"] },
  ]);
});

test("localNetworks de-duplicates a LAN and leaves virtual adapters out", () => {
  const networks = localNetworks({
    en0: [{ family: "IPv4", internal: false, address: "192.168.1.10", netmask: "255.255.255.0" }],
    en1: [{ family: "IPv4", internal: false, address: "192.168.1.11", netmask: "255.255.255.0" }],
    docker0: [{ family: "IPv4", internal: false, address: "172.17.0.1", netmask: "255.255.0.0" }],
    "vEthernet (Default Switch)": [{ family: "IPv4", internal: false, address: "172.28.32.1", netmask: "255.255.240.0" }],
    lo: [{ family: "IPv4", internal: true, address: "127.0.0.1", netmask: "255.0.0.0" }],
  });
  assert.deepEqual(networks, [{
    cidr: "192.168.1.0/24",
    interfaceNames: ["en0", "en1"],
    addresses: ["192.168.1.10", "192.168.1.11"],
  }]);
});
