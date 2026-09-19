# Release notes

## 1.5.0 — 2026-09-19

- **Cancel now actually stops a cloud upload.** Pressing Cancel during
  "Send to cloud" told the cloud console to cancel the job, and then
  uploaded every remaining segment anyway — gigabytes over a venue's
  connection, after you asked it to stop — before finally reporting
  "upload failed". The upload now stops immediately, including the segment
  already in flight, and the row says "Stopping…" the moment you click,
  settling to "Cancelled" once the job has really stopped. Cancel also
  works now on a job that was started before the app was last restarted;
  previously it silently did nothing.
- **A scan that finds nothing now tells you why.** "Nothing found on this
  network" was equally true whether there are no cameras here, the cameras
  are on a different network, or the Wi-Fi you're on deliberately hides
  devices from each other — and only one of those is something you can fix
  yourself. The app now works out which, and on a guest network that hides
  its devices it says so and tells you what to ask the venue for. It shows
  the numbers behind that reading, so you can check it.
- **A machine that can't encrypt stored passwords now says so once.** On a
  machine with no OS keyring available, camera passwords and cloud tokens
  have always been saved as plain text — there is nowhere else to put
  them — but nothing ever told you. The Log tab now gets one line the
  first time it happens.
- **Connecting to the cloud console now fails with a real sentence.**
  "Connect to the cloud console" or a rename that pings the console could
  show raw technical text like "TypeError: fetch failed". It now says one
  of three things depending on what actually happened: no internet
  connection, your sign-in has expired, or the cloud console is having
  trouble right now — each with what to do about it. A connection that
  hangs instead of failing outright now also gives up after 20 seconds
  instead of leaving "Connecting…" with no way out.
- **Fixed a frame-rate measurement that could read far higher than a
  camera's real rate.** A live-stream frame-rate check could read a steady
  30fps camera as 50+ fps if its packet spacing happened to alternate
  short and long — measured for real on a configured camera (51.55fps, then
  49fps, on a camera reporting 30 the whole time). This matters because the
  recording gate trusts this number: an over-read in the wrong direction
  could let a genuinely too-slow camera pass. Recording, calibration,
  Diagnostics, and the periodic background check all use the fixed
  calculation now.

## 1.4.0 — 2026-09-18

- **A wrong IP address now says so.** After a failed manual add, the app used
  to suggest the camera might have ONVIF switched off — unhelpful when
  nothing answered at that address at all. It now distinguishes the two and
  tells you to check the address.
- **Error messages lost their plumbing.** Failures used to appear as "Error
  invoking remote method 'cameras:add': Error: …". Just the message now. A
  stale error also no longer sits under a field you are retyping.
- **A scan that finds nothing says so** ("scan finished, nothing new found")
  instead of leaving the page looking untouched.
- **Sample clips read "File ready" in Diagnostics**, matching the rest of the
  app, rather than "Online" — there is no connection to be online.
- **"This machine" no longer says "Recording for …"** when nothing is
  recording; it says what it means, which is that the machine is connected.
- **Fixed:** the upload-speed log line said "or 395 at the slowest speed
  measured", missing the word minutes.
- **Renaming a camera no longer hides its recordings.** Recordings were
  filed in a folder named after the camera, so renaming one pointed the app
  at a folder that didn't exist: every past recording disappeared from that
  camera's page, along with the button that sends it to the cloud, while the
  files sat on disk under the old name. Recordings are now filed by camera
  rather than by name. Existing folders are moved across automatically the
  first time this version starts — in `~/pic-vision-recordings`, expect
  folders named after each camera's id instead of its label.
- **Adding a camera by IP now fails fast when the address is wrong.** Typing an
  address with nothing on it used to leave the dialog on "Connecting…" and then
  "Looking for a video stream…" — a step with no Cancel button — for about
  15 minutes before giving up. It now gives up in about 30 seconds.
- **A calibrated camera no longer reads "Not calibrated" just after launch.**
  Calibration comes from the cloud console on the app's first check-in, and a
  camera opened before that arrived showed as uncalibrated, with "Send to
  cloud" disabled and labelled "Calibrate first". The camera page now corrects
  itself, and the Refresh button on that card refreshes the calibration line
  too, not only the recordings list.

- **macOS camera discovery:** the packaged app now declares why it needs
  local-network access, allowing macOS to show the permission prompt needed
  to discover and connect to cameras. A scan reports a failure only when both
  WS-Discovery and the RTSP fallback fail.
- **Menu-bar status:** closing the macOS window now leaves a picvision icon in
  the menu bar. Its menu shows the local recording/connection state and can
  reopen or deliberately quit the agent.
- **Cloud console connection:** device registration now safely reclaims an
  existing device row and handles a concurrent retry without exposing a
  duplicate-key error. Verified in production: **Connect to the cloud
  console** works.
- **Camera status now says what's actually wrong.** Every failure used to read
  "Not answering", including a camera that was answering and refusing the
  password. Statuses are now **Sign-in needed**, **Settings unreachable**,
  **File missing** or **Not answering**, and the technical detail is in the Log
  tab rather than on the card.
- **You can re-enter a camera's password.** A camera refusing its saved
  credentials now shows a sign-in form on its detail page, verified against the
  camera before saving. Previously the only repair was removing the camera and
  adding it again, which lost its recording history and calibration.
- **Fixed:** every configured camera reported "Not answering" in 1.0.0. The
  connection check was being asked to authenticate without the stored password.
- **Security:** sign-in tokens left unencrypted by a build older than 1.0.0 are
  re-encrypted on launch, and the app's stored files are no longer readable by
  other user accounts on the same machine.

## 1.0.0 — 2026-09-06

- First downloadable unsigned Apple-silicon macOS installer for the desktop
  camera manager.
- macOS 13 (Ventura) or newer is required. On first launch, macOS may require
  **System Settings → Privacy & Security → Open Anyway** until the app is
  signed and notarized.
