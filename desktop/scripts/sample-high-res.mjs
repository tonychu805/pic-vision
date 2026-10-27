// A stand-in venue desktop for sample sessions (2026-10-27).
//
// Sample footage (a YouTube game replayed through staging) has no camera
// and no desktop, so its clips never got the sharp high-res swap or a 9:16
// version. This does the desktop's part for it: it heartbeats the console
// as an agent, takes the high-res fetches offered, trims each clip from the
// ORIGINAL sample file (standing in for the camera's main-stream
// recording), and hands it to the app's own crop-and-upload step
// (electron/highResFetch.js deliverHighRes) -- the same code a venue runs.
//
//   node --import ./electron/register-stub.mjs scripts/sample-high-res.mjs \
//     --console https://staging--picvision-console.netlify.app \
//     --token-file /path/to/agent-token \
//     --source "1=/path/original.mp4@0" --source "2=/path/original.mp4@600" ... \
//     --only /path/reel-ids.txt
//
// --source maps a part index to the sample file and the second in it where
// that part began. --only lists the sample session's reel ids, one per line:
// the console offers every unsynced clip of this agent, and a clip from
// another session must never be "sharpened" from this sample's footage.
// Runs until no fetch has been offered for --idle-sec.
// The agent token is read from a file and never printed.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { parseArgs } from "node:util";
import { FFMPEG } from "../electron/binaries.js";
import { consoleFetch } from "../electron/consoleApi.js";
import { deliverHighRes } from "../electron/highResFetch.js";

const { values } = parseArgs({
  options: {
    console: { type: "string" },
    "token-file": { type: "string" },
    source: { type: "string", multiple: true },
    only: { type: "string" },
    "idle-sec": { type: "string", default: "180" },
    "poll-sec": { type: "string", default: "20" },
  },
});
if (!values.console || !values["token-file"] || !values.source?.length || !values.only) {
  console.error("usage: --console URL --token-file FILE --source PART=FILE@OFFSET [--source ...] --only REEL_IDS_FILE");
  process.exit(2);
}
if (!/staging/.test(values.console) && !/localhost/.test(values.console)) {
  console.error("refusing: this stand-in desktop is for staging/local consoles only");
  process.exit(2);
}
const connection = { consoleUrl: values.console.replace(/\/$/, ""), apiToken: readFileSync(values["token-file"], "utf8").trim() };
const only = new Set(readFileSync(values.only, "utf8").split(/\s+/).filter(Boolean));
const sources = new Map(values.source.map((s) => {
  const m = /^(\d+)=(.+)@([\d.]+)$/.exec(s);
  if (!m) throw new Error(`bad --source ${s}`);
  return [Number(m[1]), { file: m[2], offsetSec: Number(m[3]) }];
}));

function ffmpeg(args) {
  return new Promise((resolve, reject) => {
    const p = spawn(FFMPEG, args, { stdio: ["ignore", "ignore", "pipe"] });
    let err = "";
    p.stderr.on("data", (c) => { err = (err + c).slice(-2000); });
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(err.trim().split("\n").pop()))));
  });
}

// Same encode as the app's trimHighRes (frame-accurate re-encode), from
// the sample file instead of a concatenation of camera segments.
async function trimSample(src, startSec, endSec, outPath) {
  await ffmpeg(["-y", "-v", "error", "-ss", String(src.offsetSec + startSec), "-i", src.file, "-t", String(endSec - startSec),
    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", outPath]);
}

const done = new Set();
let idleSince = Date.now();
const log = (o) => console.log(JSON.stringify({ at: new Date().toISOString(), ...o }));
while (Date.now() - idleSince < Number(values["idle-sec"]) * 1000) {
  const beat = await consoleFetch("/api/agents/heartbeat", { method: "POST", body: {}, connection });
  const fetches = (beat.pendingHighResFetches ?? []).filter((f) => only.has(f.reelId) && !done.has(f.reelId) && sources.has(f.partIndex));
  if (fetches.length) idleSince = Date.now();
  for (const f of fetches) {
    const work = mkdtempSync(path.join(tmpdir(), "sample-high-res-"));
    const clip = path.join(work, "clip.mp4");
    const t = Date.now();
    try {
      await trimSample(sources.get(f.partIndex), f.partStartSec, f.partEndSec, clip);
      const vertical = await deliverHighRes(f, clip, { label: "sample", connection });
      done.add(f.reelId);
      log({ reel: f.reelId, part: f.partIndex, vertical, sec: Math.round((Date.now() - t) / 100) / 10 });
    } catch (err) {
      log({ reel: f.reelId, part: f.partIndex, error: err.message });
      done.add(f.reelId);   // don't loop on one bad clip; the console keeps it pending
    } finally {
      rmSync(work, { recursive: true, force: true });
    }
  }
  await new Promise((r) => setTimeout(r, Number(values["poll-sec"]) * 1000));
}
log({ finished: true, delivered: done.size });
