// Pinned against error strings this app has actually produced, not
// invented ones. The 401 and the SOAP fault below are copied verbatim from
// the desktop app's own log on 2026-09-07, where two real cameras showed
// "Not answering" while live view played from both.
import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyProbeError, describeProbeState } from "./probeResult.js";

test("refused credentials are 'auth', not 'offline'", () => {
  // Verbatim from the app log: the RTSP probe's own thrown status line.
  assert.equal(classifyProbeError(new Error("RTSP/1.0 401 Unauthorized")).state, "auth");
  // Verbatim from the app log: the onvif library's SOAP fault wrapper.
  assert.equal(classifyProbeError(new Error("ONVIF SOAP Fault: Authority failure")).state, "auth");
  assert.equal(classifyProbeError(new Error("RTSP/1.0 403 Forbidden")).state, "auth");
});

test("a host that answers without a working ONVIF service is 'service'", () => {
  // Something is listening on the host but not on that port -- the RTSP
  // stream is a different port and may be perfectly fine.
  const refused = Object.assign(new Error("connect ECONNREFUSED 192.168.1.42:80"), { code: "ECONNREFUSED" });
  assert.equal(classifyProbeError(refused).state, "service");
  // The real Synology case: ONVIF lives at /Onvif/device_service (capital
  // O), so the lowercase default 404s.
  assert.equal(classifyProbeError(new Error("HTTP 404 Not Found")).state, "service");
});

test("'service' is only offered to cameras that have an ONVIF service", () => {
  // An RTSP-direct camera is probed on 554, its stream port and its only
  // port. A refusal there is the camera being down -- reporting it as
  // "answered, but its ONVIF service didn't; streaming may still work"
  // reassures the operator about the exact thing that just failed.
  const refused = Object.assign(new Error("connect ECONNREFUSED 192.168.1.42:554"), { code: "ECONNREFUSED" });
  assert.equal(classifyProbeError(refused, "rtsp").state, "offline");
  // Wrong stream path. Not "the settings service is unreachable" either.
  assert.equal(classifyProbeError(new Error("RTSP/1.0 404 Not Found"), "rtsp").state, "offline");
  // Unchanged for an ONVIF camera, and for a caller that doesn't say.
  assert.equal(classifyProbeError(refused, "onvif").state, "service");
  assert.equal(classifyProbeError(refused).state, "service");
  // Credentials still outrank connection type: a 401 is a 401 either way.
  assert.equal(classifyProbeError(new Error("RTSP/1.0 401 Unauthorized"), "rtsp").state, "auth");
});

test("a missing sample-clip file is its own state", () => {
  assert.equal(classifyProbeError(new Error("Sample clip file is missing")).state, "missing");
});

test("no answer, and anything unrecognised, is 'offline'", () => {
  assert.equal(classifyProbeError(new Error("Timed out")).state, "offline");
  assert.equal(classifyProbeError(new Error("No response")).state, "offline");
  assert.equal(
    classifyProbeError(Object.assign(new Error("connect EHOSTUNREACH"), { code: "EHOSTUNREACH" })).state,
    "offline",
  );
  // The fallback matters: an unrecognised error must not be guessed into a
  // confident state, because a wrong badge sends someone to fix the wrong
  // thing. "Didn't answer" is the honest default.
  assert.equal(classifyProbeError(new Error("something nobody has seen before")).state, "offline");
});

test("never throws, whatever it is handed", () => {
  // It runs inside a catch block; throwing here would replace a bad badge
  // with no badge at all.
  for (const input of [null, undefined, "", 0, {}, "a bare string", new Error()]) {
    assert.doesNotThrow(() => classifyProbeError(input));
    assert.equal(typeof classifyProbeError(input).state, "string");
  }
});

test("the raw message is carried in detail, never lost", () => {
  // The badge stays two words; this is what reaches the Log tab, and it's
  // the thing whose absence made the original bug undiagnosable.
  const result = classifyProbeError(new Error("RTSP/1.0 401 Unauthorized"));
  assert.equal(result.detail, "RTSP/1.0 401 Unauthorized");
});

test("log wording names the camera and implies the fix", () => {
  assert.match(describeProbeState("auth", "Court 1"), /Court 1.*username or password/);
  assert.match(describeProbeState("service", "Court 2"), /streaming may still work/);
  assert.match(describeProbeState("offline", "Court 3"), /didn't answer/);
});
