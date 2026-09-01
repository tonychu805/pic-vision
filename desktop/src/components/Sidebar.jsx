import { useEffect, useState } from "react";
import { MOCK_ALERTS } from "../data/mockData.js";
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
          {item.key === "alerts" && (
            <span className="tag tag-accent" style={{ marginLeft: "auto", padding: "1px 7px", fontSize: 10 }}>
              {MOCK_ALERTS.length}
            </span>
          )}
        </button>
      ))}

      <div
        style={{
          marginTop: "auto",
          padding: "10px 8px",
          borderRadius: "var(--radius-md)",
          background: "color-mix(in srgb, var(--color-text) 4%, transparent)",
        }}
      >
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "color-mix(in srgb, var(--color-text) 45%, transparent)",
            marginBottom: 4,
          }}
        >
          Network
        </div>
        <div style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12 }}>
          {network?.cidr ?? "Detecting…"}
        </div>
        <div style={{ fontSize: 11, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>
          {network?.interfaceName ? `Interface · ${network.interfaceName}` : " "}
        </div>
      </div>
    </div>
  );
}
