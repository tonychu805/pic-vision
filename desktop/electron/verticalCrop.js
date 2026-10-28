// Vertical (9:16) reels, cropped here from the high-res clip (operator,
// 2026-10-27: the share page's vertical clips must be high quality, and
// only this machine has the main-stream recording).
//
// The pod works out where a phone-shaped window should sit over each rally
// clip as it plays (pic-vision src/framing.py: it keeps the ball and as many
// players as fit, and starts on the server) and the console hands that path
// over with the high-res fetch. This crops the trimmed high-res clip along
// it. The window's x changes every frame, fed to ffmpeg's crop filter as
// per-frame commands (sendcmd) so it glides rather than jumping at the
// path's 5 points a second.
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { FFMPEG, FFPROBE } from "./binaries.js";

// Never upscale past this: the share page's player fills the phone anyway,
// and a taller file only costs upload time.
const MAX_OUT_HEIGHT = 1920;

/** Width in pixels of a full-height 9:16 window (even), never wider than the frame. */
export function cropWidth(w, h) {
  return Math.min(w, Math.floor(Math.round((h * 9) / 16) / 2) * 2);
}

/** Window centre (fraction of the width) at path time t, linearly interpolated, held at both ends. */
export function centreAt(framing, t) {
  const xs = framing.x;
  if (!xs.length) return 0.5;
  const f = Math.max(0, t) * framing.fps;
  const i = Math.floor(f);
  if (i >= xs.length - 1) return xs[xs.length - 1];
  return xs[i] + (xs[i + 1] - xs[i]) * (f - i);
}

/**
 * The window's left edge for every output frame. shiftSec maps the trimmed
 * clip's time onto the path's: the trim starts at partStartSec (whole
 * seconds, floored) and the path at the pod's exact clip start, so
 * shiftSec = partStartSec - clipStartSec (zero or a little negative).
 */
export function windowLefts(framing, { w, h, fps, frames, shiftSec }) {
  const cw = cropWidth(w, h);
  const out = [];
  for (let i = 0; i < frames; i++) {
    const c = centreAt(framing, i / fps + shiftSec) * w;
    out.push(Math.round(Math.min(Math.max(c - cw / 2, 0), w - cw)));
  }
  return out;
}

/** ffmpeg sendcmd script setting the crop's x on every frame. */
export function sendcmdScript(lefts, fps) {
  return lefts.map((x, i) => `${(i / fps).toFixed(4)} crop x ${x};`).join("\n") + "\n";
}

function run(bin, args) {
  return new Promise((resolve, reject) => {
    const proc = spawn(bin, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let stderrTail = "";
    proc.stdout.on("data", (chunk) => { out += chunk.toString(); });
    proc.stderr.on("data", (chunk) => { stderrTail = (stderrTail + chunk.toString()).slice(-4000); });
    proc.on("error", reject);
    proc.on("exit", (code) => {
      if (code === 0) resolve(out);
      else reject(new Error(stderrTail.trim().split("\n").pop() || `${path.basename(bin)} exited (code ${code})`));
    });
  });
}

async function probe(file) {
  const out = await run(FFPROBE, [
    "-v", "error", "-select_streams", "v:0", "-count_packets",
    "-show_entries", "stream=width,height,avg_frame_rate,nb_read_packets", "-of", "json", file,
  ]);
  const s = JSON.parse(out).streams[0];
  const [num, den] = String(s.avg_frame_rate).split("/").map(Number);
  return { w: s.width, h: s.height, fps: den ? num / den : num, frames: Number(s.nb_read_packets) };
}

/** Crop the 16:9 clip at inPath to a 9:16 clip at outPath along `framing`. */
export async function cropVertical(inPath, outPath, framing, shiftSec) {
  const { w, h, fps, frames } = await probe(inPath);
  const cw = cropWidth(w, h);
  const outH = Math.min(h, MAX_OUT_HEIGHT);
  const lefts = windowLefts(framing, { w, h, fps, frames, shiftSec });
  const workDir = mkdtempSync(path.join(tmpdir(), "pic-vision-vertical-"));
  const cmdFile = path.join(workDir, "crop.cmd");
  try {
    writeFileSync(cmdFile, sendcmdScript(lefts, fps));
    // sendcmd's file path sits inside a filter graph: escape what the graph
    // parser treats specially (Windows drive colons, backslashes, quotes).
    const escaped = cmdFile.replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "\\'");
    const vf = `sendcmd=f='${escaped}',crop=${cw}:${h}:${lefts[0] ?? 0}:0,scale=-2:${outH}:flags=lanczos`;
    await run(FFMPEG, [
      "-y", "-v", "error", "-i", inPath, "-vf", vf,
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", outPath,
    ]);
  } finally {
    rmSync(workDir, { recursive: true, force: true });
  }
}
