// Refuses to record or calibrate a camera whose frame rate is too low for
// rally detection to work, and says how to fix it.
//
// Measured, not assumed (EXPERIMENTS.md 2026-09-06): the same 5 minutes of
// footage scored precision 0.75 / recall 0.46 at 30fps and 0.60 / 0.23 at
// 15fps -- half the rallies found. No threshold recovers it. Lowering
// `min_crossings` to buy recall back reached only 0.38 recall at 0.29
// precision with a 6x false-positive rate, worse than 30fps on both axes.
// The information isn't there: half the frames means the tracker loses the
// ball more often and whole rallies fall below any sane bar.
//
// A camera left on a low factory default would otherwise halve a venue's
// results silently -- no error, just fewer highlights and no reason given.
// Better to refuse up front and point at the one setting that fixes it.
//
// Pure on purpose: no Electron, no child processes, so this runs under
// plain `node --test`. The measurement that feeds it lives in capture.js --
// importing it here dragged Electron in and broke the tests, which is how
// that was caught.

// 30fps is what every shipped constant was tuned against (config.yaml's
// `capture.fps`, `track_ball`'s max_jump, `min_crossings`), so it stays the
// target. It is a soft floor, not a hard one (operator, 2026-09-26): at the
// PGC venue on 2026-09-25 a camera set to 30 read 28 an hour later and the
// scheduled recording was refused outright -- a lost booked hour, to guard
// against a shortfall nobody has measured. Only 30 and 15 were ever scored;
// 25-28 is unmeasured, so between the two floors the camera records and the
// operator is told, rather than the session being thrown away.
import { translator } from "../i18n/index.js";

const english = translator("en");

export const MIN_FPS = 30;

// Compared with slack, for two honest reasons. 29.97 is a real, extremely
// common rate (NTSC) that means "30" everywhere in practice. And the
// measured rate is sampled over a few seconds of live video, so it carries
// noise -- warning a genuine 30fps camera because it read 29.6 would be a
// false alarm sending a venue to change a setting that is already correct.
export const WARN_BELOW_FPS = 29;

// The hard floor. 25 is the PAL-region default, so a camera left on it
// still records (with the warning); anything slower is refused. 15fps was
// measured to halve the rallies found and no threshold recovered them.
export const BLOCK_BELOW_FPS = 25;

const number = (v) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);

// Two frame rates, deliberately kept apart:
//   configured (`fps`)       -- what ONVIF says the camera is set to
//   measured (`measuredFps`) -- how many frames actually arrived, counted
//                               off the live stream (capture.js)
//
// They diverge when the network drops packets, and the right advice differs
// completely: change a camera setting, versus fix the Wi-Fi. Sending a venue
// to change a setting that is already correct wastes their time and costs
// trust, so the two cases get different messages.
//
// Measured wins what the venue is told, since detection quality depends on
// the frames that actually arrive. It does not decide the block on its own
// when the camera reports a correct setting (see isBlocked).
export function effectiveFps(camera) {
  const p = camera?.profile;
  return number(p?.measuredFps) ?? number(p?.fps);
}

// The camera is set correctly and the frames still aren't arriving: a
// network fault, which nothing else in the system would ever surface.
function isNetworkShortfall(camera) {
  const configured = number(camera?.profile?.fps);
  const measured = number(camera?.profile?.measuredFps);
  return configured !== null && configured >= WARN_BELOW_FPS && measured !== null;
}

// Blocks on a camera *set* too low, never on a network shortfall
// (operator, 2026-11-09). The measured rate comes from one 5-second probe,
// refreshed every 10 minutes, so a single Wi-Fi blip on a camera set to 30
// refused every recording until the next probe -- booked sessions included.
// A real drop during recording is still caught: the pod judges the whole
// recording and refuses one that is mostly below the floor
// (src/video_quality.py). An RTSP camera reports no setting, so what arrived
// is the only evidence of it and still blocks.
function isBlocked(camera) {
  const configured = number(camera?.profile?.fps);
  const measured = number(camera?.profile?.measuredFps);
  if (configured !== null) return configured < BLOCK_BELOW_FPS && (measured === null || measured < BLOCK_BELOW_FPS);
  return measured !== null && measured < BLOCK_BELOW_FPS;
}

// A frame rate as a person should read it: whole when it is whole (30,
// 29.97 -> 30), one decimal when rounding would lie (2026-09-29). A camera
// measured at 24.8 fps used to be shown as "25 fps" beside "recording is
// disabled" -- a number that passes, next to a verdict that it failed.
export function formatFps(v) {
  const r = Math.round(v * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/**
 * The one reading of the rule every screen shows (2026-09-29):
 *   'blocked' -- below the hard floor: recording and calibration refused
 *   'low'     -- records, with a warning
 *   'ok'
 *   'unknown' -- never measured, so not checked
 * The camera page, the camera list and Diagnostics each used to keep their
 * own copy of the thresholds; the camera page's still blocked below 29 after
 * ADR-131 lowered the floor to 25, so it told venues recording was disabled
 * on cameras that were recording.
 */
export function frameRateLevel(camera) {
  const effective = effectiveFps(camera);
  if (effective === null) return "unknown";
  if (isBlocked(camera)) return "blocked";
  if (effective < WARN_BELOW_FPS) return "low";
  return "ok";
}

// "is set to 25 fps" only when the camera said so. An RTSP camera reports no
// setting at all -- only how many frames arrived was counted.
function rateClause(camera, effective, tr) {
  const configured = number(camera?.profile?.fps);
  return configured !== null
    ? tr("fps.isSetTo", { fps: formatFps(configured) })
    : tr("fps.isSending", { fps: formatFps(effective) });
}

// Only ever blocks on a frame rate we actually know. What stays unknown --
// a sample clip (no camera at all), or a stream whose probe failed -- passes
// rather than being guessed at, since blocking a real setup over missing
// data is worse than the problem.
//
// `tr` is the translator; the operator-facing page passes its own, and
// everything else (the log, thrown errors) stays in English.
export function frameRateProblem(camera, tr = english) {
  if (!isBlocked(camera)) return null;
  const effective = effectiveFps(camera);
  const label = camera?.label ?? tr("fps.thisCamera");
  const where = camera?.hostname ? tr("fps.where.host", { host: camera.hostname }) : tr("fps.where.settings");
  return tr("fps.blocked.settings", {
    label,
    clause: rateClause(camera, effective, tr),
    block: BLOCK_BELOW_FPS,
    best: MIN_FPS,
    where,
  });
}

// Between the two floors: go ahead, but say so. No figure for how many
// rallies are lost, because none was ever measured at these rates.
export function frameRateWarning(camera, tr = english) {
  const effective = effectiveFps(camera);
  if (effective === null || effective >= WARN_BELOW_FPS || isBlocked(camera)) return null;

  const label = camera?.label ?? tr("fps.thisCamera");
  if (isNetworkShortfall(camera)) {
    return tr(effective < BLOCK_BELOW_FPS ? "fps.warn.networkLow" : "fps.warn.network", {
      label,
      best: MIN_FPS,
      block: BLOCK_BELOW_FPS,
      configured: formatFps(number(camera.profile.fps)),
      effective: formatFps(effective),
    });
  }
  return tr("fps.warn.settings", { label, best: MIN_FPS, clause: rateClause(camera, effective, tr) });
}

// Throws below the hard floor; otherwise returns the soft warning (or null)
// so the caller can log it and pass it back with its result.
export function assertUsableFrameRate(camera) {
  const problem = frameRateProblem(camera);
  if (problem) throw new Error(problem);
  return frameRateWarning(camera);
}
