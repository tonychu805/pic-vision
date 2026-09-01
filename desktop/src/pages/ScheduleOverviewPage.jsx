import { useEffect, useState } from "react";
import DayActivityStrip from "../components/DayActivityStrip.jsx";

// Overview across every configured camera: how many hours/week each is
// scheduled active, at a glance, with a way in to each camera's full
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
        Set which hours of the week each camera is active. This doesn't control live view — it defines when this camera should be included once automatic capture is built.
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
            const cells = schedules[camera.id]?.cells ?? [];
            const hoursPerWeek = cells.length;
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
                    {hoursPerWeek === 0 ? "No schedule set — treated as always off" : `${hoursPerWeek}h / week scheduled active`}
                  </div>
                </div>
                <DayActivityStrip cells={cells} />
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
