// The crash screen itself, actually rendered.
//
// This is awkward to test and gets tested anyway, on purpose. Twice in two
// days a build shipped a crash that a green suite had no opinion about,
// both times because the thing that broke was never executed by a test
// (ADR-105). The fallback UI in ErrorBoundary.jsx is the app's last line
// of defence -- if it throws, or renders nothing, or renders without an
// opaque background, the operator is back to a window that silently
// vanishes and we are back to having no idea why.
//
// The harness runs plain `node --test` with no DOM and no JSX loader, so
// the component is bundled with the esbuild already in node_modules and
// rendered through react-dom/server. No jsdom, no new dependency. The
// bundle lands inside node_modules so `react` resolves from there, and so
// nothing lands in the repo.
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
const BUNDLE = path.join(OUT_DIR, "ErrorBoundary.mjs");

let ErrorBoundary;

before(async () => {
  // Only this file's own bundle, not the whole directory. OUT_DIR is
  // shared with connectionStatus.test.js, and `node --test` runs test
  // files in parallel -- a recursive wipe here deleted that file's
  // freshly-built bundle out from under it, failing five tests with
  // ENOENT depending purely on which `before` hook won the race. It
  // passed for a while by luck, which is the worst version of this.
  mkdirSync(OUT_DIR, { recursive: true });
  rmSync(BUNDLE, { force: true });
  const result = spawnSync(
    path.join(ROOT, "node_modules", ".bin", "esbuild"),
    [path.join(ROOT, "src", "ErrorBoundary.jsx"), "--bundle", "--format=esm",
     "--jsx=automatic", "--external:react", "--external:react-dom",
     `--outfile=${BUNDLE}`, "--log-level=error"],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, `could not bundle ErrorBoundary.jsx: ${result.stderr}`);
  ({ default: ErrorBoundary } = await import(BUNDLE));
});

function renderCrashed(error) {
  const boundary = new ErrorBoundary({ children: React.createElement("div", null, "the real app") });
  // getDerivedStateFromError is what React itself calls -- used here
  // rather than hand-writing the state shape, so a change to one is a
  // change to both.
  boundary.state = { ...boundary.state, ...ErrorBoundary.getDerivedStateFromError(error) };
  return renderToStaticMarkup(boundary.render());
}

test("the crash screen shows what broke", () => {
  const html = renderCrashed(new Error("cannot read properties of undefined (reading 'dir')"));
  assert.match(html, /cannot read properties of undefined/);
  assert.match(html, /Reload the app/);
});

test("the crash screen paints an opaque background", () => {
  // The whole reason a renderer error looked like the app vanishing: this
  // window is transparent (frame:false, transparent:true, so App.jsx can
  // draw its own rounded corners). A fallback that doesn't paint its own
  // background is exactly as invisible as the unmounted tree it replaces,
  // which would make this component decorative.
  const html = renderCrashed(new Error("anything"));
  assert.match(html, /background:#16161a/, "the crash screen would be invisible on a transparent window");
  assert.match(html, /position:fixed/, "the crash screen must cover the window, not sit in the layout");
});

test("with no error it renders the app and nothing else", () => {
  // The paired half (CLAUDE.md): a boundary that swallowed its children
  // would replace one invisible-app bug with another.
  const boundary = new ErrorBoundary({ children: React.createElement("div", null, "the real app") });
  const html = renderToStaticMarkup(boundary.render());
  assert.match(html, /the real app/);
  assert.doesNotMatch(html, /Reload the app/);
});
