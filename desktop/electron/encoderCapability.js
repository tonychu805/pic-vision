// Can THIS machine encode video fast enough to be the bandwidth fallback
// (ADR-101), and with what?
//
// Recording itself never needs this (`-c copy`, capture.js) -- this only
// matters for the one scenario ADR-101 identified: a venue whose upload
// is too slow for raw footage (bandwidth.js/ADR-092) needs to shrink
// video locally before it leaves the building, and that needs an
// encoder. The question this module answers is "does the machine already
// at this venue have one fast enough, or does it need the physical
// N100/N150 fallback box (PIC-133)?"
//
// Two mistakes this is built to avoid, both already made once on this
// project:
//   1. Trusting `ffmpeg -encoders` listing a name as proof it works.
//      A name in that list means the codec was compiled in, not that a
//      driver is installed or that a VM has GPU passthrough. Encoders are
//      BENCHMARKED with a real synthetic encode, not just detected.
//   2. Hardcoding one vendor's quality knob. `-cq` (NVENC-only) turned a
//      2.70 Mbps camera stream into a 4.67 Mbps "proxy" this session --
//      -cq targets quality, not size, and is generous on already-
//      compressed input. Every candidate here is benchmarked with a
//      bitrate target (`-b:v`), which is the one flag portable across
//      every encoder family checked (VideoToolbox, QSV, NVENC, AMF,
//      libx264).
//
// Synthetic input (`lavfi testsrc`), not a real camera frame -- same
// reasoning as bandwidth.js's synthetic upload body: nothing from a
// venue's actual footage is needed to answer this question, so nothing
// real is touched.
import { spawn } from "node:child_process";
import { FFMPEG } from "./binaries.js";

// Tried in order; the first one that's both present AND fast enough
// wins. libx264 is the guaranteed floor -- present in every ffmpeg-static
// build (confirmed: macOS, Windows and Linux all bundle it), so this list
// always has an answer even with no hardware encoder at all.
const PLATFORM_CANDIDATES = {
  darwin: ["h264_videotoolbox", "libx264"],
  win32: ["h264_qsv", "h264_nvenc", "h264_amf", "libx264"],
  // The Linux ffmpeg-static build carries no hardware H.264 encoder at
  // all (checked 2026-09-09: only libx264/libx264rgb/h264_v4l2m2m, and
  // v4l2m2m needs a device node this diagnostic can't assume) -- Linux
  // is not a real venue target today, but the list stays honest about
  // what's actually in the binary rather than listing an encoder that
  // would just fail the benchmark.
  linux: ["libx264"],
};

// A camera produces ~3 Mbps (bandwidth.js's CAMERA_MBPS); the benchmark
// targets a bit above that so the measured multiplier reflects real
// encode work, not a bitrate so low the encoder barely does anything.
const BENCHMARK_BITRATE = "2M";
const BENCHMARK_SECONDS = 4;
const BENCHMARK_TIMEOUT_MS = 20_000;

// Below this, the encoder "worked" but isn't worth recommending: at 1x
// realtime it exactly keeps pace with ONE camera and falls behind the
// moment there's a second, or any transient slowdown. 1.5x leaves margin.
export const MIN_USABLE_MULTIPLIER = 1.5;

/** Raw `-encoders` text this platform's bundled ffmpeg reports. */
function listEncoderNames() {
  return new Promise((resolve) => {
    const proc = spawn(FFMPEG, ["-hide_banner", "-encoders"], { stdio: ["ignore", "pipe", "ignore"] });
    let out = "";
    proc.stdout.on("data", (c) => { out += c; });
    proc.on("close", () => resolve(out));
    proc.on("error", () => resolve(""));
  });
}

/** Does the `-encoders` listing even claim to have this one compiled in? */
export function encoderIsListed(name, encodersText) {
  return new RegExp(`^\\s*V[.\\w]*\\s+${name}\\s`, "m").test(encodersText);
}

/**
 * Actually run it: BENCHMARK_SECONDS of synthetic 1080p30 video, bitrate-
 * capped, timed wall-clock. Returns the realtime multiplier (video
 * seconds encoded per wall-clock second), or null if the encoder rejected
 * the run -- listed but non-functional (no driver, no passthrough) reads
 * as null here, same as not listed at all.
 */
export function benchmarkEncoder(name, { seconds = BENCHMARK_SECONDS, timeoutMs = BENCHMARK_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    const args = [
      "-hide_banner", "-y",
      "-f", "lavfi", "-i", `testsrc=size=1920x1080:rate=30`,
      "-t", String(seconds),
      "-c:v", name, "-b:v", BENCHMARK_BITRATE, "-maxrate", BENCHMARK_BITRATE, "-bufsize", "4M",
      "-f", "null", "-",
    ];
    const startedAt = Date.now();
    const proc = spawn(FFMPEG, args, { stdio: ["ignore", "ignore", "ignore"] });
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      const elapsedMs = Date.now() - startedAt;
      resolve(ok && elapsedMs > 0 ? (seconds * 1000) / elapsedMs : null);
    };
    const timer = setTimeout(() => { proc.kill(); finish(false); }, timeoutMs);
    proc.on("close", (code) => finish(code === 0));
    proc.on("error", () => finish(false));
  });
}

/**
 * Walks this platform's candidate list, benchmarking each until one is
 * both present and usable. Returns the winner, or the last (libx264)
 * result even if it's below MIN_USABLE_MULTIPLIER -- "here's the fastest
 * thing this machine can actually do" is the honest answer when nothing
 * clears the bar, not a null the caller has to special-case.
 */
export async function diagnoseEncodeCapability() {
  const candidates = PLATFORM_CANDIDATES[process.platform] ?? PLATFORM_CANDIDATES.linux;
  const encodersText = await listEncoderNames();

  let best = null; // last attempted result, kept as the floor answer
  for (const name of candidates) {
    if (!encoderIsListed(name, encodersText)) continue;
    const multiplier = await benchmarkEncoder(name);
    if (multiplier === null) continue; // listed but didn't actually run
    const result = { encoder: name, realtimeMultiplier: multiplier, hardware: name !== "libx264" };
    best = result;
    if (multiplier >= MIN_USABLE_MULTIPLIER) return result;
  }
  return best; // null only if literally nothing in the list would run
}
