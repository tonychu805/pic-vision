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
// visually and structurally separate (the normal gap between cells is
// left in place between them), while a single continuous booking (e.g.
// 11am-1pm, one object spanning two hours) has that same gap visually
// bridged/filled so it reads as one unbroken block -- the two cases look
// different because they *are* different (one highlight job vs. two),
// not because of an added border.
//
// CSS Grid, not nested flexbox: row/column track sizes are fixed by the
// grid definition regardless of a cell's content, so the small absolutely-
// positioned "bridge" rect that fills a gap between two same-session
// cells never perturbs row height or the hour-label gutter's alignment.
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

  // A cell's "group" identifies what it's part of: an existing session's
  // id, or a synthetic marker while it's inside the in-progress drag
  // preview. Two vertically-adjacent cells only bridge the gap between
  // them when they share the same group -- an empty cell, a different
  // session, or the edge of the grid never bridges.
  const groupAt = (day, hour) => {
    if (hour < 0 || hour > 23) return null;
    const session = sessionAt(sessions, day, hour);
    if (session) return session.id;
    if (drag && drag.day === day && hour >= drag.min && hour <= drag.max) return "preview";
    return null;
  };

  return (
    <div style={{ display: "flex", gap: GAP, userSelect: "none" }} onMouseLeave={endDrag} onMouseUp={endDrag}>
      <div style={{ display: "flex", flexDirection: "column", gap: GAP, paddingTop: 16 }}>
        {Array.from({ length: 24 }, (_, hour) => (
          <div key={hour} style={{ width: 24, height: CELL_SIZE, flex: "none", textAlign: "right", fontSize: 9.5, lineHeight: `${CELL_SIZE}px`, color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>
            {hour % HOUR_LABEL_EVERY === 0 ? hourLabel(hour) : ""}
          </div>
        ))}
      </div>

      <div>
        <div style={{ display: "flex", gap: GAP, marginBottom: GAP }}>
          {DAY_LABELS.map((label) => (
            <div key={label} style={{ width: CELL_SIZE, textAlign: "center", fontSize: 9, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
              {label[0]}
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: `repeat(7, ${CELL_SIZE}px)`, gridTemplateRows: `repeat(24, ${CELL_SIZE}px)`, gap: GAP }}>
          {Array.from({ length: 24 }, (_, hour) =>
            DAY_LABELS.map((_, day) => {
              const session = sessionAt(sessions, day, hour);
              const previewing = drag && drag.day === day && hour >= drag.min && hour <= drag.max;
              const bridgesDown = groupAt(day, hour) !== null && groupAt(day, hour) === groupAt(day, hour + 1);
              const color = previewing
                ? "color-mix(in srgb, var(--color-accent) 45%, transparent)"
                : session
                  ? "var(--color-accent)"
                  : "color-mix(in srgb, var(--color-text) 8%, transparent)";
              return (
                <div
                  key={`${day}-${hour}`}
                  onMouseDown={() => startDrag(day, hour)}
                  onMouseEnter={() => extendDrag(day, hour)}
                  title={
                    session
                      ? `${DAY_LABELS[day]} ${timeLabel(session.start)}–${timeLabel(session.end)}${session.label ? ` — ${session.label}` : ""} — click to remove`
                      : `${DAY_LABELS[day]} ${hourLabel(hour)} — drag to book a session`
                  }
                  style={{ position: "relative", width: CELL_SIZE, height: CELL_SIZE, borderRadius: 2, background: color, cursor: "pointer" }}
                >
                  {bridgesDown && (
                    <div style={{ position: "absolute", left: 0, right: 0, bottom: -GAP, height: GAP, background: color, pointerEvents: "none" }} />
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
