// Confirms a real RTSP video stream exists at a given URL -- and, given
// just credentials + a confirmed-open RTSP port, tries to find one without
// knowing the exact path in advance. Built 2026-09-01 after a real camera
// on this network turned out to have a fully working stream at rtsp://
// host:554/1 the entire day, completely independent of its ONVIF service
// (which was switched off) -- ONVIF gives a stream URL for free when it
// works, but it isn't the only way to get one.
//
// Deliberately doesn't decode video or bundle ffmpeg (heavy, a real
// packaging concern for something shipped to venue owners) -- a raw RTSP
// DESCRIBE exchange is enough to confirm a real stream is being offered.
// DESCRIBE needs Digest auth (unlike OPTIONS in discovery.js/networkSweep.js,
// which RFC 2326 exempts from credentials), so this implements that: a
// probe, a 401 challenge, then a signed retry -- the same flow curl --digest
// used manually to confirm this camera's credentials earlier the same day.
import net from "node:net";
import crypto from "node:crypto";

const DEFAULT_TIMEOUT_MS = 2500;

// A short, generic list -- conventions seen widely across camera
// firmwares (including this session's real Synology case, "/1"/"/2"), not
// a per-vendor lookup table. Deliberately NOT extended with brand-specific
// paths like Hikvision's "/Streaming/Channels/101" -- that's exactly the
// kind of vendor-curated list this project is staying away from. What
// this list can't find, the "paste your camera's own RTSP URL" fallback
// (store.js's addCameraViaRtsp with an explicit path) is for.
const COMMON_RTSP_PATHS = ["/1", "/2", "/live", "/live.sdp", "/stream1", "/video1", ""];

function md5(str) {
  return crypto.createHash("md5").update(str).digest("hex");
}

function parseAuthParams(headerValue) {
  const params = {};
  const re = /(\w+)=(?:"([^"]*)"|([^,\s]+))/g;
  let m;
  while ((m = re.exec(headerValue))) params[m[1]] = m[2] ?? m[3];
  return params;
}

function buildDigestHeader({ username, password, method, uri, realm, nonce, qop }) {
  const ha1 = md5(`${username}:${realm}:${password}`);
  const ha2 = md5(`${method}:${uri}`);
  if (qop) {
    const nc = "00000001";
    const cnonce = crypto.randomBytes(8).toString("hex");
    const response = md5(`${ha1}:${nonce}:${nc}:${cnonce}:${qop}:${ha2}`);
    return `Digest username="${username}", realm="${realm}", nonce="${nonce}", uri="${uri}", response="${response}", qop=${qop}, nc=${nc}, cnonce="${cnonce}"`;
  }
  const response = md5(`${ha1}:${nonce}:${ha2}`);
  return `Digest username="${username}", realm="${realm}", nonce="${nonce}", uri="${uri}", response="${response}"`;
}

function describeRequest(url, cseq, authHeader) {
  return [
    `DESCRIBE ${url} RTSP/1.0`,
    `CSeq: ${cseq}`,
    `User-Agent: pic-vision-desktop`,
    `Accept: application/sdp`,
    authHeader ? `Authorization: ${authHeader}` : null,
    "",
    "",
  ]
    .filter((line) => line !== null)
    .join("\r\n");
}

// A nonce is tied to the TCP connection it was issued on, not just the
// realm -- confirmed the hard way against a real server (LIVE555, this
// session's actual camera): sending the authenticated retry on a *second*,
// fresh connection got a *different* nonce back and another 401, even with
// an otherwise-correct Digest response computed from the first connection's
// nonce. So both the initial unauthenticated probe and the authenticated
// retry share one connection here; only the final result closes it.
function openRtspConnection(hostname, port, timeoutMs) {
  const socket = new net.Socket();
  let buffer = "";
  let pending = null; // { resolve, reject } for the in-flight request

  const settlePending = (value, err) => {
    if (!pending) return;
    const { resolve, reject } = pending;
    pending = null;
    err ? reject(err) : resolve(value);
  };

  socket.setTimeout(timeoutMs);
  socket.once("timeout", () => settlePending(null, new Error("Timed out")));
  socket.once("error", (e) => settlePending(null, e));
  socket.on("data", (chunk) => {
    buffer += chunk.toString("latin1");
    if (buffer.includes("\r\n\r\n")) {
      const response = buffer;
      buffer = "";
      settlePending(response);
    }
  });

  const ready = new Promise((resolve, reject) => {
    socket.once("connect", resolve);
    socket.once("error", reject);
  });
  socket.connect(port, hostname);

  return {
    async request(requestText) {
      await ready;
      return new Promise((resolve, reject) => {
        pending = { resolve, reject };
        socket.write(requestText);
      });
    },
    close() {
      socket.destroy();
    },
  };
}

// Confirms a real stream at exactly this URL -- throws if not. Returns the
// URL back (with credentials, ready to hand to a video player/recorder)
// once confirmed.
export async function describeRtspStream({ hostname, port, path, username, password, timeoutMs = DEFAULT_TIMEOUT_MS }) {
  const url = `rtsp://${hostname}:${port}${path}`;
  const conn = openRtspConnection(hostname, port, timeoutMs);
  try {
    return await describeOverConnection(conn, url, username, password);
  } finally {
    conn.close();
  }
}

async function describeOverConnection(conn, url, username, password) {
  const resp1 = await conn.request(describeRequest(url, 1));
  const status1 = (resp1.split("\r\n")[0] || "").trim();
  if (/ 200 /.test(status1)) return { url };

  const authLine = resp1.match(/WWW-Authenticate:\s*(.+)/i);
  if (!/ 401 /.test(status1) || !authLine) {
    throw new Error(status1 || "No response");
  }

  const params = parseAuthParams(authLine[1]);
  const authHeader = buildDigestHeader({
    username,
    password,
    method: "DESCRIBE",
    uri: url,
    realm: params.realm,
    nonce: params.nonce,
    qop: params.qop,
  });
  const resp2 = await conn.request(describeRequest(url, 2, authHeader));
  const status2 = (resp2.split("\r\n")[0] || "").trim();
  if (/ 200 /.test(status2)) return { url };
  throw new Error(status2 || "No response");
}

// Tries each candidate path in turn, credentials held constant -- returns
// the first working full URL, or null if none of the generic guesses
// worked (not an error: this is an optional, best-effort fallback, not a
// required step).
export async function findWorkingRtspPath({ hostname, port = 554, username, password, timeoutMs = DEFAULT_TIMEOUT_MS }) {
  for (const path of COMMON_RTSP_PATHS) {
    try {
      const { url } = await describeRtspStream({ hostname, port, path, username, password, timeoutMs });
      return { path, url };
    } catch {
      // try the next candidate
    }
  }
  return null;
}
