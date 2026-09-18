// PIC-151: what an operator is told when adding a camera goes wrong.
import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanIpcError, describeAddFailure } from "./ipcError.js";

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
