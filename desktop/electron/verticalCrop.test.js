// Vertical reels: the crop window's arithmetic, and real ffmpeg on a
// synthetic clip (never real camera footage -- same rule as
// highResFetch.test.js).
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { FFMPEG, FFPROBE } from "./binaries.js";
import { cropWidth, centreAt, windowLefts, sendcmdScript, cropVertical } from "./verticalCrop.js";

const work = mkdtempSync(path.join(tmpdir(), "vertical-crop-"));
after(() => rmSync(work, { recursive: true, force: true }));

test("the window is a full-height 9:16 slice, even, never wider than the frame", () => {
  assert.equal(cropWidth(1920, 1080), 608);
  assert.equal(cropWidth(3840, 2160), 1214);
  assert.equal(cropWidth(400, 1080), 400);
});

test("the path is interpolated between its points and held at both ends", () => {
  const f = { fps: 5, x: [0.2, 0.4] };
  assert.ok(Math.abs(centreAt(f, 0.1) - 0.3) < 1e-9);
  assert.equal(centreAt(f, -1), 0.2);
  assert.equal(centreAt(f, 10), 0.4);
  assert.equal(centreAt({ fps: 5, x: [] }, 1), 0.5);
});

test("the trim's earlier whole-second start is lined up with the pod's exact clip start", () => {
  // Path: centre 0.2 until 1 s, then 0.8. The trim started 0.6 s before the
  // pod's clip, so the jump must land 0.6 s later in the trimmed clip.
  const framing = { fps: 5, x: [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8] };
  const lefts = windowLefts(framing, { w: 1920, h: 1080, fps: 30, frames: 90, shiftSec: -0.6 });
  assert.equal(lefts[0], Math.round(0.2 * 1920 - 304));
  assert.equal(lefts[47], Math.round(0.2 * 1920 - 304));      // 1.0 s + 0.6 s, not yet moved
  assert.equal(lefts[60], Math.round(0.8 * 1920 - 304));      // moved by 2 s
});

test("the window never leaves the frame", () => {
  const lefts = windowLefts({ fps: 5, x: [0, 1] }, { w: 1920, h: 1080, fps: 30, frames: 12, shiftSec: 0 });
  assert.equal(lefts[0], 0);
  assert.equal(lefts[lefts.length - 1], 1920 - 608);
});

test("one crop command per frame, timed by the frame rate", () => {
  assert.equal(sendcmdScript([10, 20], 30), "0.0000 crop x 10;\n0.0333 crop x 20;\n");
});

// A grey frame with a white square at x 1500-1600: framing on it must put
// the square in the middle of the 9:16 output, and a wrong path must not.
function synthetic(file) {
  const r = spawnSync(FFMPEG, ["-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1920x1080:d=2:r=30",
    "-vf", "drawbox=x=1500:y=490:w=100:h=100:color=white:t=fill", "-pix_fmt", "yuv420p", file]);
  assert.equal(r.status, 0, r.stderr?.toString());
}

function brightColumns(file) {
  // One mid-clip frame as raw grey: the columns where the square shows.
  const r = spawnSync(FFMPEG, ["-v", "error", "-ss", "1", "-i", file, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    { maxBuffer: 64 * 1024 * 1024 });
  const p = spawnSync(FFPROBE, ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", file]);
  const [w, h] = p.stdout.toString().trim().split(",").map(Number);
  const row = Math.floor(h / 2);
  const cols = [];
  for (let x = 0; x < w; x++) if (r.stdout[row * w + x] > 200) cols.push(x);
  return { w, h, cols };
}

test("real ffmpeg: the crop follows the path onto the action", async () => {
  const src = path.join(work, "wide.mp4");
  synthetic(src);
  const out = path.join(work, "vertical.mp4");
  await cropVertical(src, out, { fps: 5, x: new Array(10).fill(1550 / 1920) }, 0);
  const { w, h, cols } = brightColumns(out);
  assert.equal(h, 1080);
  assert.equal(w, 608);
  assert.ok(cols.length > 50, "square visible");
  const mid = (cols[0] + cols[cols.length - 1]) / 2;
  assert.ok(Math.abs(mid - w / 2) < 10, `square centred, got ${mid}`);
});

// Paired: the same clip framed elsewhere must NOT show the square -- proves
// the window really moved with the path, not that the crop was a no-op.
test("real ffmpeg: a path pointing away leaves the square out", async () => {
  const src = path.join(work, "wide.mp4");
  const out = path.join(work, "away.mp4");
  await cropVertical(src, out, { fps: 5, x: new Array(10).fill(0.2) }, 0);
  assert.equal(brightColumns(out).cols.length, 0);
});

test("real ffmpeg: the window moves within the clip, frame by frame", async () => {
  const src = path.join(work, "wide.mp4");
  const out = path.join(work, "pan.mp4");
  // Away for the first half second, on the square by 1 s (the frame checked).
  await cropVertical(src, out, { fps: 5, x: [0.2, 0.2, 0.2, 1550 / 1920, 1550 / 1920, 1550 / 1920, 1550 / 1920, 1550 / 1920, 1550 / 1920, 1550 / 1920, 1550 / 1920] }, 0);
  const { w, cols } = brightColumns(out);
  assert.ok(cols.length > 50);
  assert.ok(Math.abs((cols[0] + cols[cols.length - 1]) / 2 - w / 2) < 10);
});
