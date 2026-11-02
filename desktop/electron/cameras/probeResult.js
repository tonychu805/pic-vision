// Turns a failed connection check into something an operator can act on.
//
// Until now every failure collapsed into one badge: CamerasPage did
// `.catch(() => "offline")`, which discarded the error object entirely and
// rendered "Not answering" for all of them. A camera replying "401
// Unauthorized" is answering -- promptly, and with the exact reason -- so
// that label sent people to check cables when the real fix was a password.
// Reported by the operator 2026-09-07: two cameras showed "Not answering"
// while live view played fine from the same cameras.
//
// The states here are chosen by WHAT THE OPERATOR SHOULD DO, not by what
// went wrong technically. Two errors with different causes but the same
// remedy belong in one bucket; two with the same cause but different
// remedies belong in two.
//
// Deliberately NOT surfacing the raw error text. That's PIC-93 -- a real
// user once saw "TypeError: fetch failed" on screen. The raw message is
// kept in `detail` for the Log tab and for support, never for the badge.
//
// No Electron imports, so this stays testable under plain `node --test`
// (the constraint frameRate.js and version.js already carry).

// TLS/OpenSSL certificate-verification failure codes, as Node sets them on
// a raw error's `.code`. Confirmed by reading how the `onvif` library
// actually surfaces a connect() failure (node_modules/onvif/lib/cam.js's
// `_requestPart2`): its `https.request`'s `error` event is handed straight
// to `connect()`'s own callback with nothing stripped or wrapped, so a TLS
// failure during an HTTPS attempt arrives here as the plain Node error,
// `.code` intact. Not ONVIF-specific -- this is Node's own OpenSSL
// verification vocabulary, plus `ERR_TLS_CERT_ALTNAME_INVALID`, which Node
// raises itself (not OpenSSL) when `checkServerIdentity` rejects a cert
// whose hostname doesn't match. `CERT_NOT_YET_VALID` and
// `UNABLE_TO_GET_ISSUER_CERT` are added here beyond what was originally
// proposed -- the same family of failure, just not every self-signed cert
// hits the exact same one.
const UNTRUSTED_CERT_CODES = new Set([
  "UNABLE_TO_VERIFY_LEAF_SIGNATURE",
  "SELF_SIGNED_CERT_IN_CHAIN",
  "DEPTH_ZERO_SELF_SIGNED_CERT",
  "CERT_HAS_EXPIRED",
  "CERT_NOT_YET_VALID",
  "UNABLE_TO_GET_ISSUER_CERT_LOCALLY",
  "UNABLE_TO_GET_ISSUER_CERT",
  "ERR_TLS_CERT_ALTNAME_INVALID",
]);

/** Whether a raw error is one of Node's certificate-verification failures. */
export function isUntrustedCertError(error) {
  return UNTRUSTED_CERT_CODES.has(error?.code);
}

/**
 * States, and the promise each one makes to the operator:
 *
 *   auth          the camera answered and refused the credentials
 *   untrustedCert the camera's ONVIF service only answers over HTTPS with a
 *                 certificate we can't verify -- not down, not wrong
 *                 credentials, a decision: accept it (self-signed certs are
 *                 the common case on real IP cameras) or fall back to RTSP
 *   service       the camera answered, but its ONVIF control service didn't --
 *                 streaming may well still work, which is the whole point of
 *                 separating this from `offline`
 *   missing       a sample clip's file is gone from disk
 *   offline       nothing answered, or we genuinely can't tell
 *
 * `connectionType` is the camera's own ('onvif' | 'rtsp' | 'sampleClip'),
 * and is what makes `service` (and `untrustedCert`) legitimate. Without it
 * this function assumed every camera was ONVIF, so an RTSP-direct camera
 * refusing a connection on 554 -- its STREAM port, the only port it has --
 * was reported as "answered, but its ONVIF service didn't; streaming may
 * still work". That is the same wrong-badge failure this file was written
 * to fix, inverted: a camera that is genuinely down, reassuringly
 * mislabelled. Omitted means unknown, which is treated as ONVIF (the
 * default and the common case).
 */
export function classifyProbeError(error, connectionType) {
  const message = String(error?.message ?? error ?? "");
  const code = error?.code ?? "";
  const hasOnvifService = connectionType !== "rtsp" && connectionType !== "sampleClip";

  // --- the file-backed case, which isn't a network problem at all ------
  if (/sample clip file is missing/i.test(message)) {
    return { state: "missing", detail: message };
  }

  // --- credentials refused --------------------------------------------
  // RTSP replies with a status line ("RTSP/1.0 401 Unauthorized"); the
  // onvif library wraps a SOAP fault ("ONVIF SOAP Fault: Authority
  // failure"). Different transports, same remedy: fix the login.
  if (
    /\b401\b|\b403\b/.test(message) ||
    /unauthorized|authority failure|not authorized|authentication/i.test(message)
  ) {
    return { state: "auth", detail: message };
  }

  // --- answered over HTTPS, but with a certificate we can't verify -----
  // Only a real signal for a camera that has an ONVIF service at all: the
  // add flow's HTTPS retry only ever runs there, so an RTSP-direct or
  // sample-clip camera can never actually produce this code.
  if (hasOnvifService && isUntrustedCertError(error)) {
    return { state: "untrustedCert", detail: message };
  }

  // --- reached the host, but not a working ONVIF service ---------------
  // ECONNREFUSED means something actively said "nothing listening here" --
  // the host is up. A 404 means the HTTP server answered but the ONVIF
  // path is wrong (a real case on this project's own Synology camera,
  // which serves /Onvif/device_service with a capital O). In both, the
  // RTSP stream on 554 is untouched and may be fine.
  //
  // Only for a camera that HAS an ONVIF service. For an RTSP-direct one
  // there is no control service to be separately unreachable: the probe
  // talks to 554, so a refusal or a 404 there is about the stream itself.
  // A 404 means the stream path is wrong rather than nothing answering --
  // worth its own state if it ever shows up in practice, but guessing at
  // one now would just be a differently-confident wrong badge, so it takes
  // the honest default below and the raw text reaches the Log tab.
  if (hasOnvifService && (code === "ECONNREFUSED" || /\b404\b|econnrefused|not found/i.test(message))) {
    return { state: "service", detail: message };
  }

  // --- genuinely no answer ---------------------------------------------
  // Timeouts and routing failures. Also the fallback: an unrecognised
  // error is reported as "couldn't reach it" rather than guessed at, since
  // a confident wrong answer sends someone to fix the wrong thing.
  return { state: "offline", detail: message };
}

/**
 * Plain-language summary for the activity log. The badge is two words; a
 * log line can afford to say what to try, and it's the one place the raw
 * detail is worth carrying.
 */
export function describeProbeState(state, label) {
  switch (state) {
    case "auth":
      return `${label} refused the saved username or password`;
    case "untrustedCert":
      return `${label} answered, but its certificate isn't trusted`;
    case "service":
      return `${label} answered, but its ONVIF service didn't — streaming may still work`;
    case "missing":
      return `${label}'s video file is missing`;
    default:
      return `${label} didn't answer`;
  }
}
