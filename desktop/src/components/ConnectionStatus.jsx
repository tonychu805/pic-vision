import { heartbeatStatus } from "../lib/heartbeatStatus.js";

// PIC-92: the line at the top of the Cloud page saying whether this
// machine is actually reporting to the console.
//
// Its own component, rather than four lines inline in CloudPage.jsx, for
// one reason: so a test can render it. CloudPage can't usefully be
// rendered on its own -- its connection arrives through an effect, and
// react-dom/server doesn't run effects -- which would leave the wording
// covered only by heartbeatStatus.test.js and the markup covered by
// nothing. That is precisely the gap ADR-105 shipped twice: an extracted
// helper with green tests, and no test executing the code around it.
const STATUS_ICON = { ok: "ph-check-circle", pending: "ph-clock-clockwise", lost: "ph-cloud-slash" };
const STATUS_COLOR = { ok: "var(--color-success)", pending: "var(--text-3)", lost: "var(--color-danger)" };

export default function ConnectionStatus({ connection }) {
  const status = heartbeatStatus(connection);
  // Loading and not-registered have their own layouts in CloudPage; this
  // component is only ever asked about a machine that has a connection.
  if (!status) return null;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <i className={`ph-fill ${STATUS_ICON[status.tone]}`} style={{ fontSize: 16, color: STATUS_COLOR[status.tone] }} />
        <span style={{ fontWeight: 500 }}>{status.title}</span>
      </div>
      <p style={{ fontSize: "var(--fs-fine)", color: "var(--text-4)", margin: "4px 0 0", lineHeight: 1.45 }}>
        {status.detail}
      </p>
    </>
  );
}
