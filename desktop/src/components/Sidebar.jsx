import { useEffect, useState } from "react";
// 2026-09-03: swapped for the white-on-transparent mark (matches the
// dark "Nocturne" sidebar background -- the old blue-on-white version
// was designed for a light background, not this one). Same
// pic-vision-cloud-console/public/pic-vision-logo-white.png used there,
// so the two apps show the same brand mark.
import logo from "../assets/pic-vision-logo-white.png";

const NAV_ITEMS = [
  { key: "cameras", label: "Cameras", icon: "ph-video-camera" },
  { key: "alerts", label: "Alerts", icon: "ph-warning-circle" },
  { key: "credentials", label: "Credentials", icon: "ph-key" },
  { key: "settings", label: "Scan settings", icon: "ph-sliders-horizontal" },
  { key: "cloud", label: "Cloud console", icon: "ph-cloud" },
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
    color: active ? "var(--color-accent-200)" : "color-mix(in srgb, var(--color-text) 72%, transparent)",
  };
}

export default function Sidebar({ nav, onNavigate, deviceCount }) {
  const [network, setNetwork] = useState(null);
  const [brandName, setBrandName] = useState(null);

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
        if (c?.brandName) return setBrandName(c.brandName);
        // Not paired to a location yet -- fall back to the signed-in
        // account's own brand (electron/auth.js's getBrand) so the
        // sidebar isn't blank between sign-in and pairing this device.
        window.authAPI?.getBrand().then((b) => setBrandName(b?.name ?? null)).catch(() => {});
      }).catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

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
        <div style={{ width: 22, height: 22, flex: "none", overflow: "hidden" }}>
          <img src={logo} alt="picvision ai" style={{ height: 22, width: "auto", maxWidth: "none" }} />
        </div>
        <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 13, letterSpacing: "-0.02em" }}>
          picvision ai
        </span>
      </div>

      {brandName && (
        <div
          style={{
            padding: "0 8px 10px",
            fontSize: 12,
            fontWeight: 500,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            color: "color-mix(in srgb, var(--color-text) 65%, transparent)",
          }}
          title={brandName}
        >
          {brandName}
        </div>
      )}

      {NAV_ITEMS.map((item) => (
        <button key={item.key} style={navButtonStyle(nav === item.key)} onClick={() => onNavigate(item.key)}>
          <i className={`ph ${item.icon}`} style={{ fontSize: 17 }} />
          {item.label}
          {item.key === "cameras" && (
            <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.6 }}>{deviceCount}</span>
          )}
        </button>
      ))}

      {/* Used to show the raw CIDR + interface name ("192.168.1.0/24" /
          "Interface · enp1s0") as the headline -- meaningless to a
          non-technical venue owner and the first thing a plain-language
          walkthrough (2026-09-01) noticed. Kept available as a hover
          tooltip for troubleshooting, not in the primary view. */}
      <div
        style={{
          marginTop: "auto",
          padding: "10px 8px",
          borderRadius: "var(--radius-md)",
          background: "color-mix(in srgb, var(--color-text) 4%, transparent)",
        }}
        title={network?.cidr ? `Network: ${network.cidr}${network.interfaceName ? ` (${network.interfaceName})` : ""}` : undefined}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <i className="ph ph-wifi-high" style={{ fontSize: 14, color: "var(--color-accent-300)" }} />
          <span style={{ fontSize: 12, fontWeight: 500 }}>
            {network?.cidr ? "Connected" : "Checking…"}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "color-mix(in srgb, var(--color-text) 45%, transparent)", marginTop: 2 }}>
          Scanning this network for cameras
        </div>
      </div>
    </div>
  );
}
