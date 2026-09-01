import { useEffect, useState } from "react";
import DayActivityStrip from "../components/DayActivityStrip.jsx";

// Overview across every configured camera: how many sessions are booked
// and how many hours, at a glance, with a way in to each camera's full
// editor. Mirrors the Cameras grid -> detail drill-down pattern already
// used elsewhere in the app rather than introducing a different nav shape.
export default function ScheduleOverviewPage({ onEditCamera }) {
  const [cameras, setCameras] = useState([]);
  const [schedules, setSchedules] = useState({});
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    const [cams, all] = await Promise.all([window.cameraAPI.list(), window.scheduleAPI.listAll()]);
    setCameras(cams);
    setSchedules(all);
    setLoading(false);
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <div style={{ marginBottom: 4, fontFamily: "var(--font-heading)", fontSize: 22 }}>Schedule</div>
      <p style={{ fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", marginTop: 0, marginBottom: 18, maxWidth: 560 }}>
        Book sessions for each camera — a 1–2pm booking and a 2–4pm booking stay separate even when they're back to back. This doesn't control live view; it defines the sessions a highlight reel will eventually be built for, once automatic capture exists.
      </p>

      {loading ? (
        <p style={{ fontSize: 13, opacity: 0.6 }}>Loading…</p>
      ) : cameras.length === 0 ? (
        <div style={{ padding: "24px 18px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
          No cameras set up yet. Add a camera from the Cameras page first, then come back here to schedule it.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {cameras.map((camera) => {
            const sessions = schedules[camera.id]?.sessions ?? [];
            const totalHours = sessions.reduce((sum, s) => sum + (s.end - s.start), 0);
            return (
              <div
                key={camera.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  padding: "12px 16px",
                  borderRadius: "var(--radius-md)",
                  background: "var(--color-surface)",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{camera.label}</div>
                  <div style={{ fontSize: 11.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
                    {sessions.length === 0
                      ? "No sessions booked yet"
                      : `${sessions.length} session${sessions.length === 1 ? "" : "s"} / week, ${totalHours}h total`}
                  </div>
                </div>
                <DayActivityStrip sessions={sessions} />
                <button className="btn btn-secondary" style={{ fontSize: 12.5, flex: "none" }} onClick={() => onEditCamera(camera)}>
                  <i className="ph ph-calendar" style={{ fontSize: 14 }} />
                  Edit schedule
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
