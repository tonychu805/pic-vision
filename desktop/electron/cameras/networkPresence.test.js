// The verdict, pinned against the situations it exists to separate.
//
// The one at the top is the real case that prompted this file: a venue's
// guest Wi-Fi on 2026-09-19, where a full sweep of the /24 found nothing
// and the app could only say "Nothing found on this network" -- a sentence
// equally true of a venue with no cameras, and one whose cameras are
// simply hidden from the machine doing the looking.
//
// Pure-function tests only: no sockets, no ARP table. Same constraint
// probeResult.test.js carries, and the reason verdictFor() takes its
// signals as arguments rather than gathering them itself.
import assert from "node:assert/strict";
import { test } from "node:test";
import { verdictFor, ISOLATION_MAX_NEIGHBORS } from "./networkPresence.js";

const silentMdns = { supported: true, peers: 0 };

test("a network where only the router is reachable is called isolated", () => {
  // The venue case. Every address on the /24 was probed by the sweep that
  // just ran; the only neighbour that resolved is the gateway.
  const verdict = verdictFor({
    cidr: "192.168.1.0/24",
    neighbors: 1,
    ssdpResponders: 0,
    mdns: silentMdns,
  });
  assert.equal(verdict.state, "isolated");
  // The remedy has to be in the text, not just the diagnosis -- no app
  // setting fixes this, so the message must send the operator to the
  // venue rather than to Scan options.
  assert.match(verdict.detail, /different network|main or camera network/i);
  assert.equal(verdict.facts.addressesChecked, 254);
});

test("silence with nothing at all in the neighbour cache is still isolated", () => {
  const verdict = verdictFor({ cidr: "192.168.1.0/24", neighbors: 0, ssdpResponders: 0, mdns: silentMdns });
  assert.equal(verdict.state, "isolated");
  // Different wording, because "the only thing visible is the router"
  // would be a claim about a router we never saw.
  assert.match(verdict.detail, /at all/);
});

test("devices visible but no camera is a different verdict, and a different remedy", () => {
  const verdict = verdictFor({ cidr: "192.168.1.0/24", neighbors: 6, ssdpResponders: 2, mdns: { supported: true, peers: 4 } });
  assert.equal(verdict.state, "no-cameras");
  // Points at the two real causes (wrong network, streaming never
  // enabled) rather than at the network's configuration.
  assert.match(verdict.detail, /different network/i);
  assert.match(verdict.detail, /switched on|turns it on/i);
});

test("one device answering a multicast question is enough to not claim isolation", () => {
  // The neighbour cache can be empty for reasons that aren't isolation --
  // entries age out, and a sweep may have been blocked by a local
  // firewall. Anything that answered anywhere overrules the claim.
  for (const signals of [
    { ssdpResponders: 1, mdns: silentMdns },
    { ssdpResponders: 0, mdns: { supported: true, peers: 1 } },
  ]) {
    const verdict = verdictFor({ cidr: "192.168.1.0/24", neighbors: 0, ...signals });
    assert.equal(verdict.state, "no-cameras");
  }
});

test("an mDNS listen that never ran doesn't count as silence", () => {
  // Binding 5353 fails where something already holds it. That's "we
  // didn't look", not "nothing was there" -- and the facts have to say
  // so rather than reporting a zero nobody measured.
  const verdict = verdictFor({
    cidr: "192.168.1.0/24",
    neighbors: 3,
    ssdpResponders: 0,
    mdns: { supported: false, peers: 0 },
  });
  assert.equal(verdict.facts.mdnsPeers, null);
  assert.equal(verdict.state, "no-cameras"); // decided on ARP alone
});

test("no network at all is its own answer, not an isolated one", () => {
  const verdict = verdictFor({ cidr: null });
  assert.equal(verdict.state, "off-network");
  assert.match(verdict.detail, /Join the venue's Wi-Fi/i);
});

test("the isolation threshold is the gateway and nothing more", () => {
  // Guards the constant itself: raising it would start calling networks
  // isolated that have real devices on them, which is the failure that
  // sends someone to argue with a venue owner about their Wi-Fi.
  assert.equal(ISOLATION_MAX_NEIGHBORS, 1);
  assert.equal(
    verdictFor({ cidr: "192.168.1.0/24", neighbors: 2, ssdpResponders: 0, mdns: silentMdns }).state,
    "no-cameras",
  );
});
