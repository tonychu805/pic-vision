import { useEffect, useState } from "react";
import logo from "../assets/pic-vision-logo.png";

const NAV_ITEMS = [
  { key: "cameras", label: "Cameras", icon: "ph-video-camera" },
  { key: "alerts", label: "Alerts", icon: "ph-warning-circle" },
  { key: "credentials", label: "Credentials", icon: "ph-key" },
  { key: "settings", label: "Scan settings", icon: "ph-sliders-horizontal" },
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

  useEffect(() => {
    window.systemAPI?.getNetworkInfo().then(setNetwork).catch(() => setNetwork(null));
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
