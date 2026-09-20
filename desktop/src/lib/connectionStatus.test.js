// PIC-92, the half heartbeatStatus.test.js can't cover: the component is
// actually built and rendered, and the assertions are on the markup an
// operator would be looking at.
//
// Worth the awkwardness for the reason ADR-105 spells out -- a refactor
// that broke the JSX around a well-tested helper shipped twice in one
// week, both times with a green suite. A tone with no icon mapped, or a
// status object read with the wrong field name, passes every test in
// heartbeatStatus.test.js and renders a blank line here.
//
// Same harness as errorBoundary.test.js: esbuild (already in
// node_modules) bundles the JSX, react-dom/server renders it. No DOM, no
// jsdom, no new dependency, and nothing written into the repo.
import assert from "node:assert/strict";
import { test, before } from "node:test";
import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const OUT_DIR = path.join(ROOT, "node_modules", ".cache", "pic-vision-tests");
const BUNDLE = path.join(OUT_DIR, "ConnectionStatus.mjs");

let ConnectionStatus;

before(async () => {
  mkdirSync(OUT_DIR, { recursive: true });
  rmSync(BUNDLE, { force: true });
  const result = spawnSync(
    path.join(ROOT, "node_modules", ".bin", "esbuild"),
    [path.join(ROOT, "src", "components", "ConnectionStatus.jsx"), "--bundle", "--format=esm",
     "--jsx=automatic", "--external:react", "--external:react-dom",
     `--outfile=${BUNDLE}`, "--log-level=error"],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, `could not bundle ConnectionStatus.jsx: ${result.stderr}`);
  ({ default: ConnectionStatus } = await import(BUNDLE));
});

const render = (connection) =>
  renderToStaticMarkup(React.createElement(ConnectionStatus, { connection }));

test("a reporting machine renders Connected, with a tick and when it checked in", () => {
  const html = render({
    brandName: "Riverside Courts",
    lastAttemptOk: true,
    lastHeartbeatAt: new Date().toISOString(),
  });
  assert.match(html, /Connected to Riverside Courts/);
  assert.match(html, /Last check-in just now/);
  assert.match(html, /ph-check-circle/, "the success icon must actually be in the markup");
});

test("a machine whose heartbeats are being rejected does not render the word Connected", () => {
  // The revoke case from the ticket. The connection record still exists,
  // which is all the old code looked at.
  const html = render({
    brandName: "Riverside Courts",
    lastAttemptOk: false,
    lastHeartbeatAt: new Date(Date.now() - 4 * 60_000).toISOString(),
  });
  assert.match(html, /Connection lost/);
  assert.match(html, /Last successful check-in 4 minutes ago/);
  assert.match(html, /ph-cloud-slash/);
  // The assertion this whole ticket comes down to.
  assert.doesNotMatch(html, /Connected to/);
});

test("a machine that hasn't checked in yet renders as connecting, not connected", () => {
  const html = render({ brandName: "Riverside Courts", lastAttemptOk: null, lastHeartbeatAt: null });
  assert.match(html, /Connecting to Riverside Courts/);
  assert.match(html, /ph-clock-clockwise/);
  assert.doesNotMatch(html, /Connected to/);
});

test("every tone maps to a real icon and colour, none render empty", () => {
  // A tone added to heartbeatStatus.js without a matching entry in the
  // two lookup tables renders `ph-fill undefined` and an invisible line,
  // which no assertion about wording would notice.
  const cases = [
    { brandName: "V", lastAttemptOk: true, lastHeartbeatAt: new Date().toISOString() },
    { brandName: "V", lastAttemptOk: false, lastHeartbeatAt: null },
    { brandName: "V", lastAttemptOk: null, lastHeartbeatAt: null },
  ];
  for (const connection of cases) {
    const html = render(connection);
    assert.doesNotMatch(html, /undefined/, `unmapped tone for ${JSON.stringify(connection)}`);
    assert.match(html, /class="ph-fill ph-[a-z-]+"/);
    assert.match(html, /color:var\(--/);
  }
});

test("the two cases the page draws itself render nothing at all", () => {
  // Paired half: if this component returned markup for "still loading" or
  // "not registered", the page would show two competing status lines.
  assert.equal(render(undefined), "");
  assert.equal(render(null), "");
});
