import { useRef, useState } from "react";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOUR_LABEL_EVERY = 3; // show a label every 3 hours, keeps the gutter readable
const CELL_SIZE = 16;
const GAP = 2;

function hourLabel(hour) {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${hour < 12 ? "am" : "pm"}`;
}

function cellKey(day, hour) {
  return `${day}-${hour}`;
}

// Interactive 7x24 weekly grid (one cell per hour per day) -- click, or
// click-and-drag across cells, to toggle a camera's active schedule. Each
// cell is a whole hour, the minimum block size; there's no finer-grained
// toggle. Read/write only -- doesn't start or stop anything real (PIC-66
// doesn't exist yet), just persists which hours a camera is scheduled active.
export default function WeekGrid({ cells, onCommit }) {
  const activeSet = cells instanceof Set ? cells : new Set(cells);
  const [draft, setDraft] = useState(null); // Set while dragging, else null (render from `cells`)
  const dragMode = useRef(null); // "activate" | "deactivate", decided by the first cell touched

  const rendered = draft ?? activeSet;

  const applyToCell = (day, hour, base) => {
    const key = cellKey(day, hour);
    const next = new Set(base);
    if (dragMode.current === "activate") next.add(key);
    else next.delete(key);
    return next;
  };

  const startDrag = (day, hour) => {
    dragMode.current = activeSet.has(cellKey(day, hour)) ? "deactivate" : "activate";
    setDraft(applyToCell(day, hour, activeSet));
  };

  const enterDuringDrag = (day, hour) => {
    if (draft === null) return;
    setDraft((prev) => applyToCell(day, hour, prev));
  };

  const endDrag = () => {
    if (draft === null) return;
    onCommit([...draft]);
    setDraft(null);
    dragMode.current = null;
  };

  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: GAP, userSelect: "none" }} onMouseLeave={endDrag} onMouseUp={endDrag}>
      <div style={{ display: "flex", gap: GAP, paddingLeft: 26 }}>
        {DAY_LABELS.map((label) => (
          <div key={label} style={{ width: CELL_SIZE, textAlign: "center", fontSize: 9, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
            {label[0]}
          </div>
        ))}
      </div>
      {Array.from({ length: 24 }, (_, hour) => (
        <div key={hour} style={{ display: "flex", gap: GAP, alignItems: "center" }}>
          <div style={{ width: 24, flex: "none", textAlign: "right", fontSize: 9.5, color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>
            {hour % HOUR_LABEL_EVERY === 0 ? hourLabel(hour) : ""}
          </div>
          {DAY_LABELS.map((_, day) => {
            const active = rendered.has(cellKey(day, hour));
            return (
              <div
                key={day}
                onMouseDown={() => startDrag(day, hour)}
                onMouseEnter={() => enterDuringDrag(day, hour)}
                title={`${DAY_LABELS[day]} ${hourLabel(hour)} — click to toggle`}
                style={{
                  width: CELL_SIZE,
                  height: CELL_SIZE,
                  borderRadius: 2,
                  background: active ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 8%, transparent)",
                  cursor: "pointer",
                }}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
