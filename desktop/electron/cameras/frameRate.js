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
// Measured wins the decision, since detection quality depends on the
// frames that actually arrive, not on what the camera intended to send.
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

// Only ever blocks on a frame rate we actually know. What stays unknown --
// a sample clip (no camera at all), or a stream whose probe failed -- passes
// rather than being guessed at, since blocking a real setup over missing
// data is worse than the problem.
export function frameRateProblem(camera) {
  const effective = effectiveFps(camera);
  if (effective === null || effective >= BLOCK_BELOW_FPS) return null;

  const label = camera?.label ?? "This camera";
  const rounded = Math.round(effective);

  if (isNetworkShortfall(camera)) {
    return (
      `${label} is set to ${number(camera.profile.fps)} fps but only about ${rounded} fps are reaching this computer. ` +
      `Rally detection needs at least ${BLOCK_BELOW_FPS} fps (${MIN_FPS} is best) -- at 15 fps it finds only half the rallies. ` +
      `The camera's own settings are fine — this is a network problem: ` +
      `check its Wi-Fi signal, or connect it by cable, then try again.`
    );
  }

  const where = camera?.hostname ? `http://${camera.hostname}` : "the camera's own settings page";
  return (
    `${label} is set to ${rounded} fps. Rally detection needs at least ${BLOCK_BELOW_FPS} fps (${MIN_FPS} is best) -- ` +
    `at 15 fps it finds only half the rallies. ` +
    `Sign in to the camera at ${where}, set the video frame rate to ${MIN_FPS}, ` +
    `then try again.`
  );
}

// Between the two floors: go ahead, but say so. No figure for how many
// rallies are lost, because none was ever measured at these rates.
export function frameRateWarning(camera) {
  const effective = effectiveFps(camera);
  if (effective === null || effective >= WARN_BELOW_FPS || effective < BLOCK_BELOW_FPS) return null;

  const label = camera?.label ?? "This camera";
  const rounded = Math.round(effective);
  if (isNetworkShortfall(camera)) {
    return (
      `${label} is set to ${number(camera.profile.fps)} fps but only about ${rounded} fps are reaching this computer. ` +
      `Recording anyway, but rally detection is tuned for ${MIN_FPS} fps and may miss some rallies -- ` +
      `check the camera's Wi-Fi signal, or connect it by cable.`
    );
  }
  return (
    `${label} is running at ${rounded} fps. Recording anyway, but rally detection is tuned for ${MIN_FPS} fps ` +
    `and may miss some rallies -- set the camera's video frame rate to ${MIN_FPS} when you can.`
  );
}

// Throws below the hard floor; otherwise returns the soft warning (or null)
// so the caller can log it and pass it back with its result.
export function assertUsableFrameRate(camera) {
  const problem = frameRateProblem(camera);
  if (problem) throw new Error(problem);
  return frameRateWarning(camera);
}
