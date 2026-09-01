import { useState } from "react";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOUR_LABEL_EVERY = 3; // show a label every 3 hours, keeps the gutter readable
const CELL_SIZE = 16;
const GAP = 2;

function hourLabel(hour) {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${hour < 12 ? "am" : "pm"}`;
}

function timeLabel(hour) {
  return hour === 24 ? "12am" : hourLabel(hour);
}

function sessionAt(sessions, day, hour) {
  return sessions.find((s) => s.day === day && hour >= s.start && hour < s.end);
}

// Interactive 7x24 weekly grid of booked sessions -- click-and-drag over
// empty cells to book a new session spanning exactly the hours dragged
// (a single click also works, booking one hour); click an existing
// session to remove it entirely. Each session is a distinct object with
// its own start/end (see electron/schedule.js), not just a flag per
// hour -- two sessions that touch with no gap (1-2pm, then 2-4pm) stay
// visually and structurally separate, marked by a divider at the start
// of each session, because each is meant to become its own highlight
// job once real capture/detection exist.
export default function WeekGrid({ sessions, onCreate, onDelete }) {
  const [drag, setDrag] = useState(null); // {day, min, max} while dragging a new session, else null

  const startDrag = (day, hour) => {
    const existing = sessionAt(sessions, day, hour);
    if (existing) {
      onDelete(existing.id);
      return;
    }
    setDrag({ day, min: hour, max: hour });
  };

  const extendDrag = (day, hour) => {
    if (drag === null || day !== drag.day) return;
    setDrag((prev) => ({ ...prev, min: Math.min(prev.min, hour), max: Math.max(prev.max, hour) }));
  };

  const endDrag = () => {
    if (drag === null) return;
    onCreate(drag.day, drag.min, drag.max + 1);
    setDrag(null);
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
            const session = sessionAt(sessions, day, hour);
            const previewing = drag && drag.day === day && hour >= drag.min && hour <= drag.max;
            const isSessionStart = session && hour === session.start;
            return (
              <div
                key={day}
                onMouseDown={() => startDrag(day, hour)}
                onMouseEnter={() => extendDrag(day, hour)}
                title={
                  session
                    ? `${DAY_LABELS[day]} ${timeLabel(session.start)}–${timeLabel(session.end)}${session.label ? ` — ${session.label}` : ""} — click to remove`
                    : `${DAY_LABELS[day]} ${hourLabel(hour)} — drag to book a session`
                }
                style={{
                  width: CELL_SIZE,
                  height: CELL_SIZE,
                  borderRadius: 2,
                  background: previewing
                    ? "color-mix(in srgb, var(--color-accent) 45%, transparent)"
                    : session
                      ? "var(--color-accent)"
                      : "color-mix(in srgb, var(--color-text) 8%, transparent)",
                  boxShadow: isSessionStart ? "inset 0 1.5px 0 var(--color-bg)" : undefined,
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
