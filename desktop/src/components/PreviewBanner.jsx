// A plain-language walkthrough (2026-09-01) flagged this as a real risk,
// not just unpolished: Alerts/Credentials/Settings show fully realistic
// sample data (fake courts, fake alerts, fake credential sets) with only a
// small gray subtitle line marking it as illustrative -- easy to miss, and
// a non-technical user skimming past it could believe something is
// actually wrong with their venue. This banner is deliberately loud (a
// filled, colored bar, not a caption) so that reading it isn't optional.
export default function PreviewBanner({ children }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        marginBottom: 14,
        borderRadius: "var(--radius-md)",
        background: "var(--color-accent-900)",
        border: "1px solid var(--color-accent-700)",
      }}
    >
      <i className="ph-fill ph-eye" style={{ fontSize: 16, color: "var(--color-accent-300)", flex: "none" }} />
      <span style={{ fontSize: 12.5, color: "var(--color-accent-100)" }}>
        <strong>Preview</strong> — {children}
      </span>
    </div>
  );
}
