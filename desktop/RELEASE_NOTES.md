# Release notes

## Unreleased

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
