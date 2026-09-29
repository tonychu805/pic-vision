import { useEffect, useState } from "react";
// 2026-09-03: swapped for the white-on-transparent mark (matches the
// dark "Nocturne" sidebar background -- the old blue-on-white version
// was designed for a light background, not this one). Same
// pic-vision-cloud-console/public/pic-vision-logo-white.png used there,
// so the two apps show the same brand mark.
import logoOnDark from "../assets/pic-vision-logo-white.png";
import logoOnLight from "../assets/pic-vision-logo.png";
import ThemeToggle from "./ThemeToggle.jsx";
import { sidebarConnection } from "../lib/heartbeatStatus.js";

// Settings is back as a peer (2026-09-29). It left when all it held was the
// Scan button's options; it has since gained "Keep this computer ready" and
// "Send in parts while recording", which decide whether a booked recording
// happens at all -- not something to file under the Cameras page's scan icon.
const NAV_ITEMS = [
  { key: "cameras", label: "Cameras", icon: "ph-video-camera" },
  { key: "log", label: "Log", icon: "ph-list-bullets" },
  { key: "diagnostics", label: "Diagnostics", icon: "ph-gauge" },
  // "This machine" rather than "Cloud console": the page is about this
  // machine's identity and who it reports for, and sign-in IS the
  // connection (ADR-096) -- naming it after the remote thing implied a
  // second place to go and connect.
  { key: "cloud", label: "This machine", icon: "ph-cloud" },
  { key: "settings", label: "Settings", icon: "ph-gear-six" },
];

function navButtonStyle(active) {
  return {
    display: "flex",
    alignItems: "center",
    gap: 9,
    width: "100%",
    padding: "7px 8px",
    border: 0,
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    font: "500 13px Inter, system-ui, sans-serif",
    textAlign: "left",
    background: active ? "color-mix(in srgb, var(--color-accent) 16%, transparent)" : "transparent",
    color: active ? "var(--color-accent-200)" : "var(--text-2)",
  };
}

export default function Sidebar({ nav, onNavigate, deviceCount, connectionEpoch = 0 }) {
  const [network, setNetwork] = useState(null);
  const [brandName, setBrandName] = useState(null);
  // The console connection, for the status box: undefined until the first
  // read, null when this machine isn't registered.
  const [connection, setConnection] = useState(undefined);

  useEffect(() => {
    window.systemAPI?.getNetworkInfo().then(setNetwork).catch(() => setNetwork(null));
  }, []);

  // Polled on the same cadence as the heartbeat that keeps it fresh
  // (cloud.js merges the console's current brand name into the stored
  // connection on every heartbeat, so a Settings-page rename shows up
  // here without restarting the app) -- window.cloudAPI.status() just
  // reads that local cache, no network call of its own.
  useEffect(() => {
    if (typeof window.cloudAPI?.status !== "function") return;
    const poll = () =>
      window.cloudAPI.status().then((c) => {
        setConnection(c ?? null);
        if (c?.brandName) return setBrandName(c.brandName);
        // Not paired to a location yet -- fall back to the signed-in
        // account's own brand (electron/auth.js's getBrand) so the
        // sidebar isn't blank between sign-in and pairing this device.
        window.authAPI?.getBrand().then((b) => setBrandName(b?.name ?? null)).catch(() => {});
      }).catch(() => {});
    poll();
    // 15s: cheap (a local read, no network call) and the status box
    // should notice a lost or removed connection soon after the heartbeat does.
    const id = setInterval(poll, 15_000);
    return () => clearInterval(id);
    // connectionEpoch re-reads immediately when the connection is
    // replaced under us (moving this machine to another venue), instead
    // of leaving the old venue's name up for the rest of the 30s tick.
  }, [connectionEpoch]);

  return (
    <div
      style={{
        width: 196,
        flex: "none",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        padding: "14px 10px",
        background: "var(--color-neutral-900)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 8px 14px" }}>
        {/* Two inks, swapped by CSS on the same conditions as the palette
            (see .brand-mark-* in index.css). The white mark was invisible
            the moment this sidebar could be light. */}
        <div style={{ width: 22, height: 22, flex: "none", overflow: "hidden" }}>
          <img className="brand-mark-on-dark" src={logoOnDark} alt="picvision ai" style={{ height: 22, width: "auto", maxWidth: "none" }} />
          <img className="brand-mark-on-light" src={logoOnLight} alt="picvision ai" style={{ height: 22, width: "auto", maxWidth: "none" }} />
        </div>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)", letterSpacing: "-0.02em" }}>
          picvision ai
        </span>
      </div>

      {NAV_ITEMS.map((item) => (
        <button key={item.key} style={navButtonStyle(nav === item.key)} onClick={() => onNavigate(item.key)}>
          <i className={`ph ${item.icon}`} style={{ fontSize: 17 }} />
          {item.label}
          {item.key === "cameras" && (
            <span style={{ marginLeft: "auto", fontSize: "var(--fs-fine)", opacity: 0.6 }}>{deviceCount}</span>
          )}
        </button>
      ))}

      <div style={{ marginTop: "auto" }}>
        <ThemeToggle />
      </div>

      {/* The console connection (2026-09-29), not the local network. This
          box used to say "Connected" about the LAN -- where anyone looks for
          "is this machine connected" -- and kept saying it while the console
          had removed the machine or couldn't be reached. The network is
          still in the tooltip for troubleshooting. Clicking opens This
          machine, where the full status and the fixes are. */}
      <button
        type="button"
        onClick={() => onNavigate("cloud")}
        style={{
          padding: "10px 8px",
          borderRadius: "var(--radius-md)",
          background: "color-mix(in srgb, var(--color-text) 4%, transparent)",
          border: "none",
          textAlign: "left",
          cursor: "pointer",
          color: "inherit",
          font: "inherit",
        }}
        title={network?.cidr ? `Network: ${network.cidr}${network.interfaceName ? ` (${network.interfaceName})` : ""}` : undefined}
      >
        <SidebarConnectionLine status={sidebarConnection(connection)} />
      </button>

      {/* Bottom-left, matching pic-vision-cloud-console's sidebar footer
          (components/app/Sidebar.tsx) -- operator's call 2026-09-06, so
          the two apps put the brand in the same place. It used to sit
          directly under the picvision mark at the top, where it read as
          part of the product's own wordmark rather than as "which brand
          am I signed in to". */}
      {brandName && (
        <div
          style={{
            padding: "10px 8px 0",
            marginTop: 12,
            borderTop: "1px solid var(--color-divider)",
            fontSize: "var(--fs-body)",
            fontWeight: 500,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={brandName}
        >
          {brandName}
        </div>
      )}
    </div>
  );
}

const TONE_ICON = { ok: "ph-cloud-check", pending: "ph-clock-clockwise", lost: "ph-cloud-slash" };
const TONE_COLOR = { ok: "var(--color-success)", pending: "var(--text-3)", lost: "var(--color-danger)" };

export function SidebarConnectionLine({ status }) {
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <i className={`ph ${TONE_ICON[status.tone]}`} style={{ fontSize: 14, color: TONE_COLOR[status.tone] }} />
        <span style={{ fontSize: "var(--fs-fine)", fontWeight: 500 }}>{status.title}</span>
      </div>
      {status.detail && (
        <div style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", marginTop: 2 }}>{status.detail}</div>
      )}
    </>
  );
}
