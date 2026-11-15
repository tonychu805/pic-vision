// Pinned against error strings this app has actually produced, not
// invented ones. The 401 and the SOAP fault below are copied verbatim from
// the desktop app's own log on 2026-09-07, where two real cameras showed
// "Not answering" while live view played from both.
import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyProbeError, describeProbeState, isUntrustedCertError } from "./probeResult.js";

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

test("isUntrustedCertError recognizes Node's own TLS verification codes", () => {
  for (const code of [
    "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
    "SELF_SIGNED_CERT_IN_CHAIN",
    "DEPTH_ZERO_SELF_SIGNED_CERT",
    "CERT_HAS_EXPIRED",
    "CERT_NOT_YET_VALID",
    "UNABLE_TO_GET_ISSUER_CERT_LOCALLY",
    "UNABLE_TO_GET_ISSUER_CERT",
    "ERR_TLS_CERT_ALTNAME_INVALID",
  ]) {
    assert.ok(isUntrustedCertError(Object.assign(new Error("tls"), { code })), code);
  }
  // A code from the same library that has nothing to do with certificates.
  assert.equal(isUntrustedCertError(Object.assign(new Error("refused"), { code: "ECONNREFUSED" })), false);
  assert.equal(isUntrustedCertError(null), false);
  assert.equal(isUntrustedCertError(new Error("no code at all")), false);
});

test("an untrusted certificate is its own state, only for a camera with an ONVIF service", () => {
  const certErr = Object.assign(new Error("unable to verify the first certificate"), {
    code: "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
  });
  assert.equal(classifyProbeError(certErr, "onvif").state, "untrustedCert");
  assert.equal(classifyProbeError(certErr).state, "untrustedCert"); // omitted connectionType defaults to ONVIF
  // An RTSP-direct or sample-clip camera never goes through the HTTPS
  // retry this code could only come from -- so it's never a real signal
  // for one, same reasoning as the 'service' state above.
  assert.equal(classifyProbeError(certErr, "rtsp").state, "offline");
  assert.equal(classifyProbeError(certErr, "sampleClip").state, "offline");
  // Credentials still outrank it, same as every other state here.
  const authErr = Object.assign(new Error("RTSP/1.0 401 Unauthorized"), { code: "UNABLE_TO_VERIFY_LEAF_SIGNATURE" });
  assert.equal(classifyProbeError(authErr, "onvif").state, "auth");
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
  assert.match(describeProbeState("untrustedCert", "Court 4"), /Court 4.*certificate/);
  assert.match(describeProbeState("service", "Court 2"), /streaming may still work/);
  assert.match(describeProbeState("offline", "Court 3"), /didn't answer/);
});
