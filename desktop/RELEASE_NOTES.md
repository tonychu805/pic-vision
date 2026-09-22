# Release notes

## 1.6.6 — 2026-09-22

- **Changed: sending two cameras' recordings to the cloud at once no
  longer slows both uploads down.** On a machine with more than one
  camera, finishing two recordings around the same time used to start
  both uploads together, competing for the same connection and making
  each one slower than sending them one after another. Uploads now go out
  one at a time, in the order they were sent; a second recording still
  gets queued for processing immediately, and its row shows "waiting for
  another upload to finish..." until its turn comes up.

## 1.6.5 — 2026-09-22

- **Fixed: Calibrate could silently stop working for every camera on a
  machine, while everything else looked fine.** The app has an instant
  push channel for console commands (Calibrate, Start/Stop recording) and
  a slower fallback poll it only uses when that channel looks disconnected.
  If the push channel died quietly — no error, nothing to notice — the app
  kept believing it was connected, so the fallback never took over: a
  Calibrate click would just sit there until the console gave up on it.
  Check-ins to the console kept succeeding the whole time, since those
  don't use the same channel, so nothing on the Cloud page ever showed a
  problem. The app now also checks in with the fallback poll every two
  minutes regardless, so this can no longer go unnoticed for longer than
  that.

## 1.6.4 — 2026-09-22

- **Fixed: adding a second camera stream from the same NVR or multi-stream
  camera did nothing.** Two RTSP streams sharing the same IP and port but a
  different path — the normal way an NVR exposes several channels — used to
  collapse into a single camera: the second "Add" just handed back the
  first one, with no new camera and no error. Cameras are now told apart by
  their full stream address (host, port, and path) instead of just the
  host. Adding the same stream twice is still recognized as one camera;
  ONVIF cameras are unaffected.

## 1.6.3 — 2026-09-21

- **Fixed: the app saying "Connected" while the console heard nothing.** A
  venue machine went quiet for over half an hour — cameras showed "Agent
  offline" on the console, and Start/Stop recording was refused — while the
  app itself still said Connected and its Log tab recorded nothing. Cause:
  the app does its work one step at a time, and several steps could wait
  forever on a network call that never answered. When one did, everything
  behind it waited too, including the check-in. Waiting forever isn't an
  error, so nothing was logged. Every wait now has a limit: a request to the
  console gives up after 30 seconds, an upload that stops moving entirely
  gives up after 60 seconds, a camera that doesn't answer is reported
  offline after 20 seconds, and a single command gives up after 2 minutes.
  The check-in no longer waits on commands for more than 15 seconds.

- **Fixed: "Calibrate" doing nothing.** A stuck command also blocked the
  ones behind it, so clicking Calibrate several times queued several
  snapshot requests that all sat unanswered. Combined with the fix above, a
  stuck request can no longer hold the queue. (The console also now reuses a
  pending request instead of queuing a duplicate, and drops snapshot
  requests nobody answered within ten minutes.)

- **Changed: the status line tells you when check-ins have stopped.** If the
  last successful check-in is more than three minutes old and nothing has
  failed since, it now says "Not checking in" with how long it has been,
  instead of "Connected".

## 1.6.2 — 2026-09-20

- **Fixed: a job stuck on "Stopping…" forever.** The row for a cloud job only
  updated while something in the app was asking the console how the job was
  doing, and that only started when an upload finished or you clicked Cancel
  — never when the app was opened. Close or restart the app after sending a
  job and its row froze at whatever it last said; for a cancelled job that
  was "Stopping…", with no Cancel or Retry button to get out of it. The app
  now picks a job back up whenever it shows one that is still in progress.
  It leaves finished jobs alone, and it stops asking if the console says the
  job no longer exists. A job whose *upload* was interrupted by closing the
  app is not picked up — that transfer died with the app and needs redoing.
  A row already stuck from before this update clears itself the first time
  you open the new version.

- **Fixed: removing a camera and adding one with the same name showed it as
  calibrated.** It wasn't — the console just hadn't been told yet. The app now
  tells the console the moment a camera is added, removed, renamed or has its
  login changed, instead of at the next 60-second check-in.

## 1.6.1 — 2026-09-20

**There is no 1.6.0 to install.** It was tagged, but its build failed before
any installer was made — the release-building machine was running an older
version of the tooling than the tests need — so nothing was ever published.
1.6.1 is that release, unchanged apart from the fix to how it gets built.

- **Fixed: getting signed out for no reason.** The app renews your login
  quietly in the background about once an hour. If that renewal failed for
  *any* reason at all — a moment of bad wifi, the login service having a
  hiccup — it threw your saved login away and made you type your password
  again. It couldn't tell "your login has genuinely expired" from "couldn't
  reach the server just then". Now only a real rejection signs you out;
  everything else keeps your login and simply tries again next time.

- **Removed the greyed-out "Keep me signed in" box.** It was never connected
  to anything, and its only explanation was a tooltip. Staying signed in is
  simply what the app does now that the bug above is fixed.

- **The Cloud page now tells you whether you are actually connected.**
  It used to say "Connected" whenever this machine had *ever* registered,
  which stays true after a machine is removed from the console — so it kept
  showing a green tick while every check-in was being turned away. It now
  says one of three things: **Connecting** (no check-in yet), **Connected**
  (the last check-in worked, and when), or **Connection lost** (and how long
  since one last worked). It refreshes itself every few seconds. The reason
  a check-in failed is still in the Log tab.

- **Renaming a camera no longer greys out its cloud buttons for a moment.**

- **Quieter in the background.** This machine now checks in with the cloud
  every 60 seconds instead of every 30, and no longer asks twice per check-in
  when its live connection is already working. The console waits three minutes
  before calling a machine offline (it used to be 90 seconds), so you will
  see "offline" a little later than before.

- Release builds now run the test suite before building the installer.

**Not yet tried on this build:** a real camera. It has been launched and its
screens checked, but only from a clean profile with no cameras set up, which
is the path that broke 1.5.0. If a camera you already have set up behaves
differently after updating, that is exactly what we need to hear about.

## 1.5.4 — 2026-09-20

- **Fixed: clicking Retry on a recording broke the interface.** This is the
  bug 1.5.3's new error screen was built to expose, and it exposed it on
  the first try: a piece of the Cancel work added two days ago was declared
  in the wrong place, so the Cancel button — which is only drawn while a
  job is running — referred to something that didn't exist. Retry starts a
  job, the button gets drawn, and the interface fell over.
- **The kind of mistake that caused it is now caught before a build is
  made.** Both crashes this week were references to a variable that didn't
  exist, and nothing in the build or the tests could see either one. A
  check for exactly that now runs ahead of the test suite. Both of this
  week's crashes were re-tested against it, and both would have been
  stopped.

## 1.5.3 — 2026-09-20

- **Fixed: the app could vanish while still running.** Clicking Retry on a
  recording made the whole app disappear — but it was never crashing. An
  error inside the interface removed everything being drawn, and because
  this window is deliberately transparent (that's how it gets its rounded
  corners), a window with nothing drawn on it isn't blank, it's invisible.
  You were seeing your desktop through it. The app kept running the whole
  time, still connected and still recording.

  The interface now catches its own errors and shows a readable screen —
  what broke, where, and a button to reload — instead of removing itself.
  Errors that screen can't catch, like a failure inside a click handler or
  a background request nobody waited on, are now recorded too.

- **Known issue: clicking Retry can still fail.** What goes wrong there is
  not fixed, because we still don't know what it is. What's changed is
  that it can no longer fail invisibly: you'll get an error on screen and
  a line in the Log tab. **If you hit it, that text is exactly what we
  need.**

## 1.5.2 — 2026-09-20

- **Known issue, not yet fixed: the app can quit when you click Retry on a
  recording.** This build does not fix that. What it does is stop it
  happening silently — see below — so the next time it happens there is
  something to read.
- **The app now says why it stopped, instead of just going away.** A crash
  in 1.5.1 produced no message at all: the window simply vanished, which
  left nothing to work from. Every way the app can stop is now written to
  the Log tab and to a `crash.log` file beside it, and it distinguishes an
  error, a background failure, the window's process dying, a helper
  process dying, and a plain quit — all of which previously looked the
  same from the outside. Some background failures could also take the app
  down with no warning at all; those are now reported and survived rather
  than fatal.

  **If the Retry crash happens to you again**, the Log tab will have a line
  for it. That line is what we need.

## 1.5.1 — 2026-09-19

- **Fixed: 1.5.0 crashed on launch.** Opening the app showed "A JavaScript
  error occurred in the main process" and it never got any further, for
  anyone with a camera set up. A variable removed during last week's
  frame-rate fix was still being used by the line that measures a camera's
  bitrate, so checking a camera's stream — which happens on launch — threw
  every time. **If you installed 1.5.0, replace it with this build.** 1.4.0
  was not affected.

## 1.5.0 — 2026-09-19 (withdrawn — crashes on launch, use 1.5.1)

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
