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

## 1.0.0 — 2026-09-06

- First downloadable unsigned Apple-silicon macOS installer for the desktop
  camera manager.
- macOS 13 (Ventura) or newer is required. On first launch, macOS may require
  **System Settings → Privacy & Security → Open Anyway** until the app is
  signed and notarized.
