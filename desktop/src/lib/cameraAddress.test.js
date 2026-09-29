// The "new address" form on a camera's page, actually rendered -- same
// esbuild + react-dom/server harness as connectionStatus.test.js, for the
// same ADR-105 reason: the markup has to be exercised, not just the store.
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
const BUNDLE = path.join(OUT_DIR, "CameraDetailPage.mjs");

let CameraAddress;

before(async () => {
  mkdirSync(OUT_DIR, { recursive: true });
  rmSync(BUNDLE, { force: true });
  const result = spawnSync(
    path.join(ROOT, "node_modules", ".bin", "esbuild"),
    [path.join(ROOT, "src", "pages", "CameraDetailPage.jsx"), "--bundle", "--format=esm",
     "--jsx=automatic", "--external:react", "--external:react-dom",
     `--outfile=${BUNDLE}`, "--log-level=error"],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, `could not bundle CameraDetailPage.jsx: ${result.stderr}`);
  ({ CameraAddress } = await import(BUNDLE));
});

const render = (camera) => renderToStaticMarkup(React.createElement(CameraAddress, { camera }));

test("the form starts from the camera's current address and says what is kept", () => {
  const html = render({ id: "c1", label: "Court 1", hostname: "192.168.1.20", port: 554 });
  assert.match(html, /Did this camera get a new address\?/);
  assert.match(html, /value="192.168.1.20"/);
  assert.match(html, /value="554"/);
  assert.match(html, /calibration and recordings are kept/);
});

// Paired: the warning that makes keeping the calibration safe must be there,
// and saving the unchanged address must not be possible.
test("it warns that a moved camera needs calibrating, and won't save an unchanged address", () => {
  const html = render({ id: "c1", label: "Court 1", hostname: "192.168.1.20", port: 554 });
  assert.match(html, /a camera that was moved needs calibrating again/);
  assert.match(html, /<button[^>]*disabled[^>]*>Use this address<\/button>/);
});
