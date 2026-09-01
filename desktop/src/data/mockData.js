// Sample data for pages that don't have a real backend yet (Alerts,
// Credentials, Settings) -- ported verbatim from the Claude Design mockup
// (desktop-utility-by-claude-design.zip, "Camera Manager.dc.html") rather
// than invented, so it stays traceable to the source design. These pages
// are visual-only: pixel-matched to the mockup, not wired to real data or
// real actions. See desktop/README.md for what's real vs. illustrative.

export const MOCK_ALERTS = [
  { icon: "ph-fill ph-plugs", iconColor: "var(--color-accent-2-400)", title: "Court 5 stopped answering", detail: "IP5M-T1179E · 10.0.4.61 · no reply on port 554 for 41 minutes — no highlights captured since", when: "11:02", action: "Re-probe" },
  { icon: "ph-fill ph-lock-simple", iconColor: "var(--color-accent-2-400)", title: "Sign-in refused twice", detail: "Unassigned camera · 10.0.4.33 · saved set “Venue default” rejected", when: "10:47", action: "Fix" },
  { icon: "ph ph-arrow-circle-up", iconColor: "var(--color-accent-300)", title: "Firmware 11.11.94 available", detail: "Court 2 · baseline · currently 11.7.18", when: "09:15", action: "Update" },
  { icon: "ph ph-check-circle", iconColor: "color-mix(in srgb, var(--color-text) 35%, transparent)", title: "Court 3 recovered", detail: "IPC-HDW3849 · stream resumed after a 3 min gap", when: "Yesterday", action: "Dismiss" },
  { icon: "ph ph-clock-clockwise", iconColor: "color-mix(in srgb, var(--color-text) 35%, transparent)", title: "Clock drift corrected", detail: "Three cameras were 4 min behind · NTP set to pool.ntp.org", when: "Yesterday", action: "Dismiss" },
];

export const MOCK_CREDENTIALS = [
  { name: "Venue default", user: "admin", usedBy: "4 cameras", verified: "2 min ago" },
  { name: "Axis court cams", user: "root", usedBy: "3 cameras", verified: "2 min ago" },
  { name: "Venue staff", user: "operator", usedBy: "None yet", verified: "Never" },
  { name: "Legacy Dahua", user: "888888", usedBy: "1 camera", verified: "Yesterday" },
];

export const MOCK_RANGES = [
  { cidr: "10.0.4.0/24", note: "this machine", icon: "ph ph-wifi-high" },
  { cidr: "10.0.9.0/24", note: "camera VLAN", icon: "ph ph-network" },
  { cidr: "192.168.1.0/24", note: "factory default range", icon: "ph ph-plug" },
];

// Unlike the other 3 mock-data exports, this list is a mix -- ONVIF
// WS-Discovery and the RTSP port sweep are both real (electron/cameras/
// discovery.js, networkSweep.js), everything else is still illustrative.
// `real: true` drives SettingsPage.jsx's per-row labeling.
export const MOCK_PROTOCOLS = [
  { name: "ONVIF WS-Discovery", note: "multicast", enabled: true, real: true },
  { name: "RTSP port sweep", note: "port 554, every host in the subnet", enabled: true, real: true },
  { name: "RTSP protocol confirm", note: "OPTIONS handshake, no credentials — separates a real RTSP responder from anything else on the port", enabled: true, real: true },
  { name: "mDNS / Bonjour", note: "multicast", enabled: true },
  { name: "SSDP / UPnP", note: "multicast", enabled: true },
  { name: "Vendor probes", note: "Axis, Hikvision, Dahua, Reolink", enabled: true },
  { name: "RTSP stream probe", note: "confirms a found camera's stream actually plays, not just that it speaks RTSP", enabled: false },
];
