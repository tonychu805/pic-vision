// Turning a thrown error into something an operator should read.
//
// Two separate problems, both found by UAT on 2026-09-18 (PIC-151).
//
// 1. Electron wraps everything that crosses the IPC boundary:
//      "Error invoking remote method 'cameras:add': Error: Network timeout"
//    That prefix was reaching the screen verbatim, on top of otherwise
//    perfectly good sentences -- including the Scan settings validation
//    message, which reads fine on its own.
//
// 2. After a failed manual add, the dialog always blamed ONVIF being
//    switched off. For a mistyped address nothing answered at all, so that
//    sends someone into a camera's settings menu hunting for a toggle that
//    was never the problem.

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
