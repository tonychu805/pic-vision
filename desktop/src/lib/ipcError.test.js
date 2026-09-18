// PIC-151: what an operator is told when adding a camera goes wrong.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanIpcError, describeAddFailure, describeRegisterError } from "./ipcError.js";

test("Electron's IPC wrapper is stripped", () => {
  // Verbatim from the UAT session, 2026-09-18.
  assert.equal(
    cleanIpcError(new Error("Error invoking remote method 'cameras:add': Error: Network timeout")),
    "Network timeout",
  );
  assert.equal(
    cleanIpcError(new Error("Error invoking remote method 'scanSettings:addRange': Error: Enter an address like 192.168.1.50 or a range like 192.168.1.0/24")),
    "Enter an address like 192.168.1.50 or a range like 192.168.1.0/24",
  );
});

test("a message that was never wrapped is left alone", () => {
  assert.equal(cleanIpcError(new Error("Already recording this camera")), "Already recording this camera");
});

test("an empty or missing error still says something", () => {
  // Better a vague sentence than a blank red line that looks like a bug.
  assert.equal(cleanIpcError(new Error("")), "Something went wrong.");
  assert.equal(cleanIpcError(null), "Something went wrong.");
  assert.equal(cleanIpcError(undefined), "Something went wrong.");
});

test("a non-Error value is handled", () => {
  assert.equal(cleanIpcError("plain string failure"), "plain string failure");
});

test("nothing answering is not blamed on ONVIF", () => {
  // The regression: a mistyped address used to be met with "this camera
  // might have ONVIF turned off", sending someone into a settings menu for
  // a camera that isn't there.
  const { title, body } = describeAddFailure(
    new Error("Error invoking remote method 'cameras:add': Error: Network timeout"),
    "192.0.2.1",
  );
  assert.match(title, /Nothing answered at 192\.0\.2\.1/);
  assert.match(body, /Check the address is right/);
  assert.doesNotMatch(body, /ONVIF turned off/);
});

test("connection-level failures all count as nothing answering", () => {
  for (const message of ["connect ETIMEDOUT 192.0.2.1:554", "connect ECONNREFUSED 10.0.0.9:80", "getaddrinfo ENOTFOUND camera.local"]) {
    assert.match(describeAddFailure(new Error(message), "10.0.0.9").title, /Nothing answered/, message);
  }
});

test("a camera that did answer still gets the ONVIF advice", () => {
  // This is the case the original wording was written for, and it stays.
  const { title, body } = describeAddFailure(new Error("ONVIF SOAP Fault: Action not supported"), "192.168.1.42");
  assert.equal(title, "Couldn't connect automatically");
  assert.match(body, /ONVIF turned off/);
  assert.match(body, /192\.168\.1\.42/);
});

test("the address is left out gracefully when unknown", () => {
  assert.match(describeAddFailure(new Error("Network timeout"), "").title, /Nothing answered at that address/);
});

// PIC-93: what an operator is told when connecting this machine to the
// cloud console fails. cloud.js's registerAgentOnce classifies the real
// failure into one of three sentinel words before it ever crosses IPC
// (see cloud.test.js for that half) -- these tests are the other side,
// the plain-language mapping the renderer actually shows.
test("each classified failure gets a plain, actionable sentence", () => {
  assert.match(describeRegisterError(new Error("network")), /check your internet connection/);
  assert.match(describeRegisterError(new Error("auth")), /sign.*out.*sign.*back in/i);
  assert.match(describeRegisterError(new Error("server")), /try again in a few minutes/i);
});

test("the classified word itself never reaches the screen", () => {
  // A regression here would be a real one: showing the bare code "server"
  // or "auth" instead of translating it would be as confusing as the raw
  // text this was built to replace.
  for (const code of ["network", "auth", "server"]) {
    assert.notEqual(describeRegisterError(new Error(code)), code);
  }
});

test("the IPC wrapper is stripped before classifying, same as everywhere else", () => {
  assert.match(
    describeRegisterError(new Error("Error invoking remote method 'cloud:register': Error: server")),
    /try again in a few minutes/i,
  );
});

test("a genuinely unclassified error still says something real, not a guess", () => {
  // Anything reaching here that ISN'T one of the three sentinel words is a
  // failure this classification scheme didn't anticipate -- shown as-is
  // (cleaned of IPC plumbing) rather than silently mapped to the wrong
  // bucket, or swallowed.
  assert.equal(describeRegisterError(new Error("something truly unexpected")), "something truly unexpected");
});
