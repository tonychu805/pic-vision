// A venue LAN isn't always a /24.
//
// Asked 2026-09-09: what happens when a camera sits on 10.17.x.x? The
// answer depended entirely on the netmask, and one case was bad. Scan
// derives its range from the interface (system.js's guessCidr), so a
// 255.0.0.0 mask makes that range 10.0.0.0/8 -- and the size cap used to
// be applied to `hostsInCidr(cidr).length`, which builds the list before
// anyone checks whether it should. Measured on a dev workstation:
// 16,777,214 strings, 6.5 seconds, ~1 GB of RSS, and only then a refusal.
// That happens in the main process, which is also where recording and the
// heartbeat live.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_HOSTS, hostCount, hostsInCidr, sweepNetwork } from "./networkSweep.js";

test("counting agrees with listing, where listing is affordable", () => {
  // The arithmetic has to mean the same thing as the list it replaced,
  // or the cap moves silently.
  for (const cidr of ["192.168.1.0/24", "10.17.3.0/24", "10.17.0.0/23", "10.0.0.0/30"]) {
    assert.equal(hostCount(cidr), hostsInCidr(cidr).length, cidr);
  }
});

test("a /31 and a /32 have no usable hosts", () => {
  assert.equal(hostCount("10.17.3.0/31"), 0);
  assert.equal(hostCount("10.17.3.4/32"), 0);
  assert.equal(hostsInCidr("10.17.3.0/31").length, 0);
});

test("the private ranges a venue actually uses", () => {
  assert.equal(hostCount("192.168.1.0/24"), 254);
  assert.equal(hostCount("10.17.3.0/24"), 254, "a class-A address on a /24 is an ordinary 254-host LAN");
  assert.equal(hostCount("10.17.0.0/16"), 65534);
  assert.equal(hostCount("10.0.0.0/8"), 16777214);
});

test("an oversized range is refused without being built", async () => {
  // The regression this guards: the same refusal used to cost 6.5s and
  // ~1 GB first. A generous ceiling -- building the list can't finish
  // anywhere near this fast, so the check can only pass if nothing was
  // built.
  const startedAt = Date.now();
  await assert.rejects(
    () => sweepNetwork({ cidr: "10.0.0.0/8" }),
    /Refusing to sweep 16777214 addresses/,
  );
  const elapsed = Date.now() - startedAt;
  assert.ok(elapsed < 1000, `refusal took ${elapsed}ms -- the address list is being built before the cap is checked`);
});

test("a /16 is refused too, and says what to do about it", async () => {
  await assert.rejects(
    () => sweepNetwork({ cidr: "10.17.0.0/16" }),
    (err) => {
      assert.match(err.message, /65534 addresses/);
      assert.match(err.message, new RegExp(`cap is ${MAX_HOSTS}`));
      return true;
    },
  );
});
