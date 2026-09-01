import { useEffect, useState } from "react";
import WeekGrid from "../components/WeekGrid.jsx";

const ALL_CELLS = Array.from({ length: 7 }, (_, day) => Array.from({ length: 24 }, (_, hour) => `${day}-${hour}`)).flat();

// Full per-camera weekly schedule editor -- click or click-drag any hour
// cell to toggle it active/inactive, persisted immediately on each
// click/drag-release via scheduleAPI (electron/schedule.js).
export default function ScheduleEditorPage({ camera, onBack }) {
  const [cells, setCells] = useState(null); // null while loading
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    window.scheduleAPI.get(camera.id).then((s) => setCells(s.cells));
  }, [camera.id]);

  const commit = async (nextCells) => {
    setCells(nextCells); // optimistic -- IPC round-trip to the same value would just flicker
    await window.scheduleAPI.set(camera.id, nextCells);
    setSavedAt(Date.now());
  };

  const hoursPerWeek = cells?.length ?? 0;

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <button className="btn btn-ghost" style={{ fontSize: 12.5, marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />Schedule overview
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
        <div>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 22 }}>{camera.label}</div>
          <div style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            Click a cell, or click and drag, to toggle an hour on or off.
          </div>
        </div>
        {savedAt && <span className="tag tag-accent" style={{ flex: "none" }}>Saved</span>}
      </div>

      {cells === null ? (
        <p style={{ fontSize: 13, opacity: 0.6, marginTop: 16 }}>Loading…</p>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "14px 0" }}>
            <span style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
              {hoursPerWeek}h / week scheduled active
            </span>
            <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => commit(ALL_CELLS)}>Activate all</button>
            <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => commit([])}>Clear all</button>
          </div>

          <div style={{ padding: 16, borderRadius: "var(--radius-md)", background: "var(--color-surface)", display: "inline-block" }}>
            <WeekGrid cells={cells} onCommit={commit} />
          </div>
        </>
      )}
    </div>
  );
}
