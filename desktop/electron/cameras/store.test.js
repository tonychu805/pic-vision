// Covers the ONVIF three-tier retry ladder in testConnection() (plain HTTP,
// strict HTTPS, HTTPS with the operator's explicit go-ahead to skip
// verification) and addCamera()'s persistence of that go-ahead.
//
// No module-mocking machinery needed: `onvif` is a CJS package, and both
// store.js's `import onvifPromises from "onvif/promises/index.js"` and this
// file's `import rawOnvif from "onvif/lib/cam.js"` resolve to the same
// cached module instance (Node's CJS require cache is keyed by resolved
// path, and ESM import of a CJS file goes through the same cache). The
// `Cam` class `promises/cam.js` wraps internally -- `require('../lib/cam').
// Cam` -- is the exact object reachable here as `rawOnvif.Cam`, so
// monkey-patching its prototype controls every connect attempt
// testConnection makes, without ever touching a real network. Same style
// as the rest of this file's tests (synthetic errors, no snapshots) -- just
// applied to a class instead of a plain object.
import assert from "node:assert/strict";
import { test } from "node:test";
import rawOnvif from "onvif/lib/cam.js";
import { testConnection, addCamera } from "./store.js";

const RawCam = rawOnvif.Cam;

// Which tier a connect() attempt belongs to -- the exact three shapes
// connectOnvif's retry ladder produces (store.js): useSecure=false is the
// first, plain-HTTP attempt; useSecure=true with no secureOpts is the
// second, strict-HTTPS attempt; useSecure=true with rejectUnauthorized:false
// is the third, only reached once the operator has already said yes.
function tierOf(cam) {
  if (!cam.useSecure) return "http";
  if (cam.secureOpts && cam.secureOpts.rejectUnauthorized === false) return "unverified";
  return "httpsStrict";
}

// Installs a fake connect() -- and the two calls testConnection makes right
// after a connect succeeds -- for one test, then restores the real
// prototype methods. `connect(tier)` returns an Error to fail that tier, or
// a falsy value to succeed it.
function mockOnvif(t, { connect, deviceInfo = {} }) {
  const originalConnect = RawCam.prototype.connect;
  const originalDeviceInfo = RawCam.prototype.getDeviceInformation;
  const originalStreamUri = RawCam.prototype.getStreamUri;

  RawCam.prototype.connect = function (callback) {
    callback(connect(tierOf(this)) || null);
  };
  RawCam.prototype.getDeviceInformation = function (callback) {
    callback(null, deviceInfo);
  };
  // Never actually exercised by these tests (cam.profiles/.activeSource
  // stay unset, so subStreamInfo's own early-return skips a second call) --
  // failing it exercises the tolerance testConnection already has for a
  // camera that needs a profile token before it hands back a stream URI.
  RawCam.prototype.getStreamUri = function (options, callback) {
    (callback ?? options)(new Error("no profile token"));
  };

  t.after(() => {
    RawCam.prototype.connect = originalConnect;
    RawCam.prototype.getDeviceInformation = originalDeviceInfo;
    RawCam.prototype.getStreamUri = originalStreamUri;
  });
}

const HTTP_REFUSED = Object.assign(new Error("connect ECONNREFUSED 10.0.0.5:80"), { code: "ECONNREFUSED" });
const UNTRUSTED_CERT = Object.assign(new Error("unable to verify the first certificate"), {
  code: "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
});

test("an untrusted cert with no consent throws the HTTPS error, not the HTTP one", async (t) => {
  mockOnvif(t, {
    connect: (tier) =>
      tier === "http" ? HTTP_REFUSED : tier === "httpsStrict" ? UNTRUSTED_CERT : new Error("must not reach this tier"),
  });
  // This is the exact trap the brief calls out: the "obviously consistent"
  // choice -- rethrow the HTTP error, same as the two-tier ladder always
  // did -- would mean classifyProbeError never sees a cert code, and the
  // consent prompt could never fire. The HTTPS error is the only one that
  // carries it.
  await assert.rejects(testConnection({ hostname: "10.0.0.5", username: "u", password: "p" }), (err) => {
    assert.equal(err, UNTRUSTED_CERT);
    return true;
  });
});

test("acceptUnverifiedCert resolves normally once the unverified attempt succeeds", async (t) => {
  mockOnvif(t, {
    connect: (tier) => (tier === "http" ? HTTP_REFUSED : tier === "httpsStrict" ? UNTRUSTED_CERT : null),
    deviceInfo: { manufacturer: "Acme", model: "Cam1" },
  });
  const result = await testConnection({
    hostname: "10.0.0.5",
    username: "u",
    password: "p",
    acceptUnverifiedCert: true,
  });
  assert.equal(result.info.manufacturer, "Acme");
});

test("an unrelated HTTPS failure still throws the HTTP error, same as the two-tier ladder", async (t) => {
  const httpErr = new Error("Network timeout");
  const unrelatedHttpsErr = Object.assign(new Error("connect ECONNREFUSED 10.0.0.5:443"), { code: "ECONNREFUSED" });
  mockOnvif(t, { connect: (tier) => (tier === "http" ? httpErr : unrelatedHttpsErr) });
  await assert.rejects(testConnection({ hostname: "10.0.0.5", username: "u", password: "p" }), (err) => {
    assert.equal(err, httpErr);
    return true;
  });
});

test("when the accepted attempt itself fails for some other reason, falls back to the HTTP error", async (t) => {
  const httpErr = new Error("Network timeout");
  const unverifiedAttemptErr = new Error("Network timeout");
  mockOnvif(t, {
    connect: (tier) => (tier === "http" ? httpErr : tier === "httpsStrict" ? UNTRUSTED_CERT : unverifiedAttemptErr),
  });
  await assert.rejects(
    testConnection({ hostname: "10.0.0.5", username: "u", password: "p", acceptUnverifiedCert: true }),
    (err) => {
      // Not the cert error, and not the unverified-attempt's own error --
      // back to the one the operator already recognizes from the plain
      // two-tier ladder.
      assert.equal(err, httpErr);
      return true;
    },
  );
});

test("addCamera persists acceptUnverifiedCert, so a later background check never needs to re-prompt", async (t) => {
  mockOnvif(t, { connect: () => null, deviceInfo: { manufacturer: "Acme", model: "Cam1" } });
  const camera = await addCamera({
    hostname: "10.0.0.9",
    username: "u",
    password: "p",
    acceptUnverifiedCert: true,
  });
  assert.equal(camera.acceptUnverifiedCert, true);
});

test("addCamera defaults acceptUnverifiedCert to false when it was never passed", async (t) => {
  mockOnvif(t, { connect: () => null, deviceInfo: { manufacturer: "Acme", model: "Cam2" } });
  const camera = await addCamera({ hostname: "10.0.0.10", username: "u", password: "p" });
  assert.equal(camera.acceptUnverifiedCert, false);
});
