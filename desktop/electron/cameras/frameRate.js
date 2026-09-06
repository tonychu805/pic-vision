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

// 30fps is what every shipped constant was tuned against (config.yaml's
// `capture.fps`, `track_ball`'s max_jump, `min_crossings`). 24 is the floor
// rather than 30 so a 25fps (PAL-region) camera still works: it's within
// reach of the tuning, unlike 15. Note the honest gap -- 30 and 15 are
// measured, everything between them is inference from those two points, so
// this line is a judgement call, not a measured cliff.
export const MIN_FPS = 24;
export const RECOMMENDED_FPS = 30;

// Only ever blocks on a frame rate we actually know. A camera added through
// the RTSP fallback never went through ONVIF and reports no profile; a
// sample clip has no camera at all. Guessing for those would block real
// setups over missing data, so they pass.
export function frameRateProblem(camera) {
  const fps = camera?.profile?.fps;
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) return null;
  if (fps >= MIN_FPS) return null;

  const where = camera.hostname ? `http://${camera.hostname}` : "the camera's own settings page";
  return (
    `${camera.label} is set to ${fps} fps. Rally detection needs at least ${MIN_FPS} fps ` +
    `(${RECOMMENDED_FPS} is recommended) — at ${fps} fps it finds roughly half the rallies. ` +
    `Sign in to the camera at ${where}, set the video frame rate to ${RECOMMENDED_FPS}, ` +
    `then try again.`
  );
}

export function assertUsableFrameRate(camera) {
  const problem = frameRateProblem(camera);
  if (problem) throw new Error(problem);
}
