import { useEffect, useState } from "react";

// Real activity history (2026-09-05, replacing the mock "Alerts" page --
// see electron/activityLog.js for what actually writes these and why:
// every event type here is a real signal already computed somewhere in
// the app -- camera online/offline, recording, calibration, cloud
// pipeline jobs, cloud console connectivity, sign-in/out. No fake action
// buttons, no illustrative PreviewBanner -- this is real now.
//
// Icon/color per event type, same "derive from a fixed set of states"
// shape as cameraView.js's STATE_META -- but with an explicit fallback
// (STATE_META's own lack of one crashed the app once, 2026-09-01, the
// first time a card was built missing a field it indexed on without
// guarding).
const EVENT_META = {
  camera_online: { icon: "ph ph-check-circle", color: "var(--color-accent-400)" },
  camera_offline: { icon: "ph ph-plugs", color: "var(--color-accent-2-400)" },
  recording_started: { icon: "ph ph-record", color: "var(--color-accent-400)" },
  recording_stopped: { icon: "ph ph-stop-circle", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" },
  recording_failed: { icon: "ph ph-warning-circle", color: "var(--color-accent-2-400)" },
  calibration_done: { icon: "ph ph-check-circle", color: "var(--color-accent-400)" },
  calibration_failed: { icon: "ph ph-warning-circle", color: "var(--color-accent-2-400)" },
  pipeline_started: { icon: "ph ph-cloud-arrow-up", color: "var(--color-accent-300)" },
  pipeline_done: { icon: "ph ph-check-circle", color: "var(--color-accent-400)" },
  pipeline_failed: { icon: "ph ph-warning-circle", color: "var(--color-accent-2-400)" },
  cloud_connected: { icon: "ph ph-cloud-check", color: "var(--color-accent-400)" },
  cloud_disconnected: { icon: "ph ph-cloud-slash", color: "var(--color-accent-2-400)" },
  signed_in: { icon: "ph ph-sign-in", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" },
  signed_out: { icon: "ph ph-sign-out", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" },
};
const DEFAULT_META = { icon: "ph ph-info", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" };

const POLL_INTERVAL_MS = 5000;

function formatWhen(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : d.toLocaleDateString();
}

export default function LogPage() {
  const [events, setEvents] = useState(null); // null = loading

  const refresh = () => window.logAPI?.list().then(setEvents).catch(() => setEvents([]));

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const clear = async () => {
    await window.logAPI?.clear();
    refresh();
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "16px 22px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2 }}>Log</div>
        {events && events.length > 0 && (
          <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: 12.5 }} onClick={clear}>
            Clear log
          </button>
        )}
      </div>

      {events === null ? (
        <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Loading…</p>
      ) : events.length === 0 ? (
        <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
          Nothing yet — camera status changes, recordings, calibrations, and cloud jobs will show up here as they happen.
        </p>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          {events.map((e) => {
            const meta = EVENT_META[e.type] || DEFAULT_META;
            return (
              <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
                <i className={meta.icon} style={{ fontSize: 18, color: meta.color, flex: "none" }} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 500 }}>{e.title}</div>
                  {e.detail && (
                    <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {e.detail}
                    </div>
                  )}
                </div>
                <span style={{ flex: "none", fontSize: 11.5, fontFamily: "ui-monospace, Menlo, monospace", color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>
                  {formatWhen(e.at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
