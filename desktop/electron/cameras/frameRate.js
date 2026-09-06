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
// `capture.fps`, `track_ball`'s max_jump, `min_crossings`). 24 is the floor
// rather than 30 so a 25fps (PAL-region) camera still works: it's within
// reach of the tuning, unlike 15. Note the honest gap -- 30 and 15 are
// measured, everything between them is inference from those two points, so
// this line is a judgement call, not a measured cliff.
export const MIN_FPS = 24;
export const RECOMMENDED_FPS = 30;

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
// Measured wins the pass/fail decision, since detection quality depends on
// the frames that actually arrive, not on what the camera intended to send.
export function effectiveFps(camera) {
  const p = camera?.profile;
  return number(p?.measuredFps) ?? number(p?.fps);
}

// Only ever blocks on a frame rate we actually know. What stays unknown --
// a sample clip (no camera at all), or a stream whose probe failed -- passes
// rather than being guessed at, since blocking a real setup over missing
// data is worse than the problem.
export function frameRateProblem(camera) {
  const effective = effectiveFps(camera);
  if (effective === null || effective >= MIN_FPS) return null;

  const configured = number(camera?.profile?.fps);
  const measured = number(camera?.profile?.measuredFps);
  const label = camera?.label ?? "This camera";
  const rounded = Math.round(effective);

  // The camera is set correctly and the frames still aren't arriving. This
  // is a network fault, and nothing else in the system would ever surface
  // it -- the recording would simply succeed and the reel would be thin.
  if (configured !== null && configured >= MIN_FPS && measured !== null) {
    return (
      `${label} is set to ${configured} fps but only about ${rounded} fps are reaching this computer. ` +
      `That halves the rallies found. The camera's own settings are fine — this is a network problem: ` +
      `check its Wi-Fi signal, or connect it by cable, then try again.`
    );
  }

  const where = camera?.hostname ? `http://${camera.hostname}` : "the camera's own settings page";
  return (
    `${label} is set to ${rounded} fps. Rally detection needs at least ${MIN_FPS} fps ` +
    `(${RECOMMENDED_FPS} is recommended) — at ${rounded} fps it finds roughly half the rallies. ` +
    `Sign in to the camera at ${where}, set the video frame rate to ${RECOMMENDED_FPS}, ` +
    `then try again.`
  );
}

export function assertUsableFrameRate(camera) {
  const problem = frameRateProblem(camera);
  if (problem) throw new Error(problem);
}
