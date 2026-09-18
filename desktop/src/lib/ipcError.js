// Turning a thrown error into something an operator should read.
//
// Three separate problems have landed here so far.
//
// 1. Electron wraps everything that crosses the IPC boundary (PIC-151,
//    2026-09-18):
//      "Error invoking remote method 'cameras:add': Error: Network timeout"
//    That prefix was reaching the screen verbatim, on top of otherwise
//    perfectly good sentences -- including the Scan settings validation
//    message, which reads fine on its own.
//
// 2. After a failed manual add, the dialog always blamed ONVIF being
//    switched off (PIC-151). For a mistyped address nothing answered at
//    all, so that sends someone into a camera's settings menu hunting for
//    a toggle that was never the problem.
//
// 3. Connecting this machine to the cloud console could surface literally
//    "Error invoking remote method 'cloud:register': TypeError: fetch
//    failed" (PIC-93, filed 2026-09-05) -- meaningless to a venue
//    operator, and not even that useful to a technical one, since it
//    doesn't say what was being reached or why. Unlike 1/2, this one
//    isn't fixable by pattern-matching the message text alone: a 500 here
//    is very often a raw Postgres error with no marker distinguishing it
//    from a real, addressable one -- see `describeRegisterError`'s own
//    comment for why the classification has to happen on the main-process
//    side instead, at the one place that still has the HTTP status.

const IPC_WRAPPER = /^Error invoking remote method '[^']*':\s*(?:[A-Za-z]*Error:\s*)?([\s\S]*)$/

/** The message without Electron's IPC plumbing around it. */
export function cleanIpcError(err) {
  const raw = String(err?.message ?? err ?? '').trim()
  const unwrapped = raw.match(IPC_WRAPPER)?.[1] ?? raw
  return unwrapped.trim() || 'Something went wrong.'
}

// Nothing answered: the connection never got far enough for anything to
// reply. Kept separate from "answered, but not the way we hoped" because
// only the second one is worth mentioning ONVIF for.
const NOTHING_ANSWERED = /network timeout|timed out|etimedout|econnrefused|ehostunreach|enetunreach|enotfound|getaddrinfo/i

/**
 * What to tell someone whose manual "add camera" attempt failed, after both
 * the ONVIF attempt and the generic RTSP path list came up empty.
 * Returns { title, body } -- the dialog's own heading and paragraph.
 */
export function describeAddFailure(err, hostname) {
  const where = hostname ? `at ${hostname}` : 'at that address'
  if (NOTHING_ANSWERED.test(cleanIpcError(err))) {
    return {
      title: `Nothing answered ${where}`,
      body:
        `Check the address is right, and that the camera is powered on and on the same network as this machine. ` +
        `If the address is correct and it still doesn't answer, and your camera's app shows a video stream address ` +
        `(sometimes called an "RTSP URL" or "stream URL"), you can paste it here to add it directly.`,
    }
  }
  return {
    title: "Couldn't connect automatically",
    body:
      `The camera answered ${where}, but not in a way this app could set up on its own — it might have ONVIF turned ` +
      `off. Check its own app or settings for a network option called "ONVIF" and make sure it's on, then try again ` +
      `above. In the meantime, if your camera's app shows you a video stream address (sometimes called an "RTSP URL" ` +
      `or "stream URL"), you can paste it here to add it directly.`,
  }
}

// What to tell someone whose "Connect to the cloud console" attempt
// failed, once `cloud.js`'s `registerAgentOnce` has already classified it.
//
// That classification happens in the main process, not by matching the
// message text here, because a message-text guess would get this wrong in
// the one case that matters most: a server error there is very often a raw
// Postgres error string (the console API's own known gap, PIC-144) with
// nothing in the wording to distinguish it from a real, addressable 4xx.
// The main process still has the HTTP status at the moment it throws; by
// the time an error reaches here, that's gone -- so it throws one of three
// short, deliberate words instead of the real message, and puts the real
// message in the Log tab via `logEvent` (same split `classifyProbeError`
// already uses for camera failures -- PIC-93's own resolution note names
// that as the pattern to copy).
//
// Anything else reaching here (a thrown message that ISN'T one of the
// three words below) is genuinely unclassified -- shown via `cleanIpcError`
// rather than silently guessed at, so a real, unanticipated failure still
// says something rather than nothing.
const REGISTER_ERROR_MESSAGES = {
  network: "Couldn't reach the cloud console — check your internet connection and try again.",
  auth: "Your sign-in may have expired. Sign out and sign back in, then try connecting again.",
  server: "The cloud console is having trouble right now. Try again in a few minutes.",
}

export function describeRegisterError(err) {
  const code = cleanIpcError(err)
  return REGISTER_ERROR_MESSAGES[code] ?? code
}
