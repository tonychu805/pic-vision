import { useEffect, useState } from "react";

// Real activity history (2026-09-05, replacing the mock "Alerts" page --
// see electron/activityLog.js for what actually writes these and why:
// every event type here is a real signal already computed somewhere in
// the app -- camera online/offline, recording, calibration, cloud
// pipeline jobs, cloud console connectivity, sign-in/out. No fake action
// buttons, no illustrative PreviewBanner -- this is real now.
//
// Icon/tone per event type, same "derive from a fixed set of states"
// shape as cameraView.js's STATE_META -- but with an explicit fallback
// (STATE_META's own lack of one crashed the app once, 2026-09-01, the
// first time a card was built missing a field it indexed on without
// guarding).
//
// `tone` replaces the per-type literal colours this used to carry
// (2026-09-06). Every failure was drawn in --color-accent-2-400, a muted
// lavender a shade away from the success colour, so a failed pipeline job
// and a finished one looked alike at a glance -- the whole point of
// scanning a log. Tones now map to the semantic tokens in index.css.
const EVENT_META = {
  camera_online: { icon: "ph ph-check-circle", tone: "ok" },
  camera_offline: { icon: "ph ph-plugs", tone: "bad" },
  recording_started: { icon: "ph ph-record", tone: "ok" },
  recording_stopped: { icon: "ph ph-stop-circle", tone: "quiet" },
  recording_failed: { icon: "ph ph-warning-circle", tone: "bad" },
  calibration_done: { icon: "ph ph-check-circle", tone: "ok" },
  calibration_failed: { icon: "ph ph-warning-circle", tone: "bad" },
  pipeline_started: { icon: "ph ph-cloud-arrow-up", tone: "info" },
  pipeline_done: { icon: "ph ph-check-circle", tone: "ok" },
  pipeline_failed: { icon: "ph ph-warning-circle", tone: "bad" },
  cloud_connected: { icon: "ph ph-cloud-check", tone: "ok" },
  cloud_disconnected: { icon: "ph ph-cloud-slash", tone: "bad" },
  signed_in: { icon: "ph ph-sign-in", tone: "quiet" },
  signed_out: { icon: "ph ph-sign-out", tone: "quiet" },
};
const DEFAULT_META = { icon: "ph ph-info", tone: "quiet" };

const TONE_COLOR = {
  ok: "var(--color-success)",
  bad: "var(--color-danger)",
  info: "var(--color-accent-300)",
  quiet: "var(--text-3)",
};

const POLL_INTERVAL_MS = 5000;

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

// Day heading for a group. Older entries used to render a bare date with
// no time at all, so a two-day-old failure couldn't be lined up against a
// recording -- the date moves up here and every row keeps its clock time.
function dayLabel(dayStart) {
  const today = startOfDay(new Date());
  const dayMs = 86_400_000;
  if (dayStart === today) return "Today";
  if (dayStart === today - dayMs) return "Yesterday";
  const d = new Date(dayStart);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

// activityLog.js unshifts, so `events` arrives newest-first and stays
// that way inside each day -- this only has to cut the run into days, not
// re-sort it.
function groupByDay(events) {
  const groups = [];
  for (const e of events) {
    const day = startOfDay(new Date(e.at));
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.events.push(e);
    else groups.push({ day, events: [e] });
  }
  return groups;
}

// A detail line is usually the reason something failed -- the one part of
// the row worth reading when a job breaks. It used to be clipped to one
// line with no way to see the rest (no tooltip, no expand), so the
// answer was always just off-screen. Rows that have one are now buttons
// that toggle the full text.
function LogRow({ event }) {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[event.type] || DEFAULT_META;
  const color = TONE_COLOR[meta.tone] ?? TONE_COLOR.quiet;
  const time = new Date(event.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  const body = (
    <>
      <i className={meta.icon} style={{ fontSize: 15, color, flex: "none", marginTop: 1 }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: "var(--fs-strong)", fontWeight: 500, color: meta.tone === "bad" ? "var(--color-danger)" : undefined }}>
          {event.title}
        </div>
        {event.detail && (
          <div
            className="text-3"
            style={{
              fontSize: "var(--fs-fine)",
              ...(expanded
                ? { whiteSpace: "pre-wrap", wordBreak: "break-word" }
                : { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }),
            }}
          >
            {event.detail}
          </div>
        )}
      </div>
      <span className="mono text-4" style={{ flex: "none", fontSize: "var(--fs-fine)" }}>{time}</span>
    </>
  );

  const rowStyle = {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    width: "100%",
    textAlign: "left",
    padding: "8px 0",
    border: 0,
    borderTop: "1px solid var(--hairline)",
    background: "transparent",
    font: "inherit",
    color: "inherit",
  };

  if (!event.detail) return <div style={rowStyle}>{body}</div>;
  return (
    <button
      type="button"
      style={{ ...rowStyle, cursor: "pointer" }}
      onClick={() => setExpanded((v) => !v)}
      title={expanded ? "Hide the full message" : event.detail}
    >
      {body}
    </button>
  );
}

export default function LogPage() {
  const [events, setEvents] = useState(null); // null = loading
  const [confirmingClear, setConfirmingClear] = useState(false);

  const refresh = () => window.logAPI?.list().then(setEvents).catch(() => setEvents([]));

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  // Two-step, matching CameraDetailPage's RemoveCameraControl -- this is
  // the only record of what the pipeline did and clearing it can't be
  // undone (electron-store, no history), so it shouldn't go on one click
  // of a button sitting in the corner where the mouse already is.
  const clear = async () => {
    await window.logAPI?.clear();
    setConfirmingClear(false);
    refresh();
  };

  const groups = events ? groupByDay(events) : [];

  return (
    <div className="page-fixed">
      <div className="page-head">
        <div className="page-title">Log</div>
        {events && events.length > 0 && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {confirmingClear ? (
              <>
                <span className="text-3" style={{ fontSize: "var(--fs-body)" }}>Delete all {events.length} entries?</span>
                <button className="btn btn-secondary" style={{ fontSize: "var(--fs-fine)" }} onClick={() => setConfirmingClear(false)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  style={{ fontSize: "var(--fs-fine)", color: "var(--color-danger)", borderColor: "var(--color-danger)" }}
                  onClick={clear}
                >
                  Clear log
                </button>
              </>
            ) : (
              <button className="btn btn-ghost" style={{ fontSize: "var(--fs-body)" }} onClick={() => setConfirmingClear(true)}>
                Clear log
              </button>
            )}
          </div>
        )}
      </div>

      {events === null ? (
        <p className="page-sub">Loading…</p>
      ) : events.length === 0 ? (
        <p className="page-sub">
          Nothing yet — camera status changes, recordings, calibrations, and cloud jobs will show up here as they happen.
        </p>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
          {groups.map((group) => (
            <div key={group.day}>
              <div className="section-label section-label-quiet" style={{ marginBottom: 4 }}>{dayLabel(group.day)}</div>
              <div className="card" style={{ padding: "2px 14px 8px" }}>
                {group.events.map((e) => <LogRow key={e.id} event={e} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
