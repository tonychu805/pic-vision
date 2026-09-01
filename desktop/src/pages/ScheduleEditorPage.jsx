import { useEffect, useState } from "react";
import WeekGrid from "../components/WeekGrid.jsx";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function hourLabel(hour) {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${hour < 12 ? "am" : "pm"}`;
}

function timeLabel(hour) {
  return hour === 24 ? "12am" : hourLabel(hour);
}

function sortedSessions(sessions) {
  return [...sessions].sort((a, b) => a.day - b.day || a.start - b.start);
}

// One row in the session list -- shows the booked time range, an editable
// label (defaults to a placeholder, not a fabricated name), and a delete
// button. Redundant with clicking the session directly on the grid, but
// more discoverable and the only way to rename one.
function SessionRow({ session, onRename, onDelete }) {
  const [label, setLabel] = useState(session.label ?? "");

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
      <span className="tag tag-outline" style={{ flex: "none", width: 34, justifyContent: "center" }}>{DAY_LABELS[session.day]}</span>
      <span style={{ flex: "none", width: 118, fontSize: 12.5, fontFamily: "ui-monospace, Menlo, monospace" }}>
        {timeLabel(session.start)}–{timeLabel(session.end)}
      </span>
      <input
        className="input"
        style={{ flex: 1, minHeight: 28, fontSize: 12.5 }}
        placeholder="Untitled session"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onBlur={() => onRename(session.id, label)}
      />
      <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => onDelete(session.id)}>
        <i className="ph ph-trash" style={{ fontSize: 14 }} />
      </button>
    </div>
  );
}

// Full per-camera session editor -- click-and-drag any range of hour
// cells to book a session, click an existing one to remove it, each
// persisted immediately via scheduleAPI (electron/schedule.js). The list
// below the grid is the same data, sorted, with rename/delete controls.
export default function ScheduleEditorPage({ camera, onBack }) {
  const [sessions, setSessions] = useState(null); // null while loading
  const [savedAt, setSavedAt] = useState(null);

  const reload = () => window.scheduleAPI.list(camera.id).then(setSessions);

  useEffect(() => {
    reload();
  }, [camera.id]);

  const createSession = async (day, start, end) => {
    const next = await window.scheduleAPI.add(camera.id, { day, start, end });
    setSessions(next);
    setSavedAt(Date.now());
  };

  const deleteSession = async (sessionId) => {
    const next = await window.scheduleAPI.remove(camera.id, sessionId);
    setSessions(next);
    setSavedAt(Date.now());
  };

  const renameSession = async (sessionId, label) => {
    const next = await window.scheduleAPI.rename(camera.id, sessionId, label);
    setSessions(next);
    setSavedAt(Date.now());
  };

  const totalHours = sessions?.reduce((sum, s) => sum + (s.end - s.start), 0) ?? 0;

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <button className="btn btn-ghost" style={{ fontSize: 12.5, marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />Schedule overview
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 22 }}>{camera.label}</div>
          <div style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            Drag across cells to book a session. Click a booked session to remove it.
          </div>
        </div>
        {savedAt && <span className="tag tag-accent" style={{ flex: "none" }}>Saved</span>}
      </div>

      {sessions === null ? (
        <p style={{ fontSize: 13, opacity: 0.6, marginTop: 16 }}>Loading…</p>
      ) : (
        <>
          <div style={{ display: "flex", gap: 24, marginTop: 14, alignItems: "flex-start" }}>
            <div style={{ padding: 16, borderRadius: "var(--radius-md)", background: "var(--color-surface)", flex: "none" }}>
              <WeekGrid sessions={sessions} onCreate={createSession} onDelete={deleteSession} />
            </div>

            <div style={{ flex: 1, minWidth: 260, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 4 }}>
                Sessions
              </div>
              <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", marginBottom: 10 }}>
                {sessions.length === 0 ? "None booked yet" : `${sessions.length} session${sessions.length === 1 ? "" : "s"}, ${totalHours}h total`}
              </div>
              {sessions.length === 0 ? (
                <p style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 45%, transparent)", margin: 0 }}>
                  Drag across the grid to book one — each booking becomes its own highlight reel once automatic capture is built.
                </p>
              ) : (
                sortedSessions(sessions).map((s) => (
                  <SessionRow key={s.id} session={s} onRename={renameSession} onDelete={deleteSession} />
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
