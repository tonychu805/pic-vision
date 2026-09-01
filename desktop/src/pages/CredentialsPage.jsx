import PreviewBanner from "../components/PreviewBanner.jsx";
import { MOCK_CREDENTIALS } from "../data/mockData.js";

export default function CredentialsPage() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "16px 22px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
        <div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2 }}>Credentials</div>
        </div>
        <button className="btn btn-primary" style={{ marginLeft: "auto", cursor: "not-allowed" }} disabled>
          <i className="ph ph-plus" style={{ fontSize: 15 }} />Add set
        </button>
      </div>
      <PreviewBanner>a saved login for each camera is entered when you add it, on the Cameras page — this table is a sample of a future shortcut, not real.</PreviewBanner>
      <table className="table" style={{ marginTop: 10, opacity: 0.55 }}>
        <thead>
          <tr><th>Name</th><th style={{ width: 130 }}>User</th><th style={{ width: 110 }}>Password</th><th style={{ width: 120 }}>Used by</th><th style={{ width: 140 }}>Last verified</th></tr>
        </thead>
        <tbody>
          {MOCK_CREDENTIALS.map((c) => (
            <tr key={c.name}>
              <td><span style={{ fontWeight: 500 }}>{c.name}</span></td>
              <td style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5 }}>{c.user}</td>
              <td style={{ letterSpacing: "0.15em", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>••••••••</td>
              <td style={{ fontSize: 13 }}>{c.usedBy}</td>
              <td style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>{c.verified}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
