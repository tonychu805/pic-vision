import PreviewBanner from "../components/PreviewBanner.jsx";
import { MOCK_RANGES, MOCK_PROTOCOLS } from "../data/mockData.js";

export default function SettingsPage() {
  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "16px 22px 26px" }}>
      <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2, marginBottom: 4 }}>Scan settings</div>
      <PreviewBanner>
        "Scan again" on the Cameras page already checks your whole network automatically — there's nothing to
        configure yet. The options below are a sample of future controls, not real ones.
      </PreviewBanner>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "start", opacity: 0.55 }}>
        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Ranges</div>
          {MOCK_RANGES.map((r) => (
            <div key={r.cidr} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
              <i className={r.icon} style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5 }}>{r.cidr}</span>
              <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>{r.note}</span>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input className="input" placeholder="192.168.1.0/24" style={{ flex: 1 }} disabled />
            <button className="btn btn-secondary" disabled style={{ cursor: "not-allowed" }}>Add</button>
          </div>
        </div>

        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>How scanning works</div>
          {MOCK_PROTOCOLS.map((p) => (
            <label key={p.name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", fontSize: 13, borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
              <i
                className={p.enabled ? "ph-fill ph-check-square" : "ph ph-square"}
                style={{ fontSize: 16, color: p.enabled ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 30%, transparent)" }}
              />
              <span style={{ fontWeight: 500 }}>{p.name}</span>
              <span style={{ fontSize: 11.5, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>{p.note}</span>
            </label>
          ))}
        </div>

        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Behaviour</div>
          <label className="radio" style={{ display: "flex", padding: "6px 0" }}><input type="radio" name="beh" defaultChecked disabled /><span className="dot" />Scan when picvision opens</label>
          <label className="radio" style={{ display: "flex", padding: "6px 0" }}><input type="radio" name="beh" disabled /><span className="dot" />Re-scan every 15 minutes</label>
          <label className="radio" style={{ display: "flex", padding: "6px 0" }}><input type="radio" name="beh" disabled /><span className="dot" />Only when I ask</label>
          <div className="field" style={{ marginTop: 12 }}><label>Per-address timeout</label><input className="input" defaultValue="5000 ms" disabled /></div>
        </div>

        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Previews</div>
          <p style={{ fontSize: 12, lineHeight: 1.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: 0 }}>
            This app doesn't decode live video previews — see the camera detail page's Streams panel for the raw
            RTSP URL instead.
          </p>
        </div>
      </div>
    </div>
  );
}
