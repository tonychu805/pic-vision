// Camera addresses carry their password (rtsp://user:pass@host/...), and
// ffmpeg names its input when it fails: "rtsp://user:pass@192.168.2.3:554/1:
// Connection refused". That line became an error message, went into the Log
// tab and, as a command result, into the console's database (one row,
// 2026-09-29). Everything that turns tool output into a message goes through
// here, and so does everything that leaves the app (logEvent, command results).
//
// Same marker as redactStreamUri (cameras/store.js): "***:***@" keeps the
// shape, so "this camera uses credentials" stays visible. Greedy to the last
// @ before the path, because a password may itself contain @.
const URL_USERINFO = /\b([a-z][a-z0-9+.-]*:\/\/)[^\s/]*@/gi;
const PASSWORD_PARAM = /([?&](?:password|passwd|pwd|pass)=)[^&\s"']*/gi;

export function redactCredentials(value) {
  if (typeof value === "string") return value.replace(URL_USERINFO, "$1***:***@").replace(PASSWORD_PARAM, "$1***");
  if (Array.isArray(value)) return value.map(redactCredentials);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactCredentials(v)]));
  }
  return value;
}

/** The last line a tool printed to stderr, without credentials, or `fallback` when it printed nothing. */
export function lastStderrLine(stderrTail, fallback) {
  return redactCredentials((stderrTail || "").trim().split("\n").pop()) || fallback;
}
