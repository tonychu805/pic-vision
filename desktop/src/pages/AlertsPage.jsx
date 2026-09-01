import { MOCK_ALERTS } from "../data/mockData.js";

export default function AlertsPage() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "16px 22px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2 }}>Alerts</div>
          <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            Illustrative — no alert monitoring is built yet
          </div>
        </div>
        <div className="seg" style={{ marginLeft: "auto" }}>
          <label className="seg-opt"><input type="radio" name="alertf" defaultChecked />Open</label>
          <label className="seg-opt"><input type="radio" name="alertf" />All</label>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {MOCK_ALERTS.map((a, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
            <i className={a.icon} style={{ fontSize: 18, color: a.iconColor }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 13.5, fontWeight: 500 }}>{a.title}</div>
              <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{a.detail}</div>
            </div>
            <span style={{ fontSize: 11.5, fontFamily: "ui-monospace, Menlo, monospace", color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>{a.when}</span>
            <button className="btn btn-secondary" style={{ fontSize: 12.5 }}>{a.action}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
