import { useState } from "react";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOUR_LABEL_EVERY = 3; // show a label every 3 hours, keeps the gutter readable
const CELL_SIZE = 16;
const GAP = 2;
const STEP = CELL_SIZE + GAP; // pixel distance from one hour row/day column to the next

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

// Pixel geometry for a day+[start,end) span, matching the grid below --
// one real rectangle per session, not a stack of per-hour cells, so a
// continuous multi-hour booking renders as one shape with rounded corners
// only on its true outer edges instead of repeating at every hour boundary
// (a per-cell-rounded stack still reads as multiple pieces even with no
// gap between them).
function spanRect(day, start, end) {
  return { left: day * STEP, top: start * STEP, width: CELL_SIZE, height: (end - start) * CELL_SIZE + (end - start - 1) * GAP };
}

// Interactive 7x24 weekly grid of booked sessions -- click-and-drag over
// empty cells to book a new session spanning exactly the hours dragged
// (a single click also works, booking one hour); click an existing
// session to remove it entirely. Each session is a distinct object with
// its own start/end (see electron/schedule.js), not just a flag per
// hour -- rendered as one real rectangle (spanRect) laid over an
// invisible interaction grid, not as separate per-hour cells, so a
// continuous booking (11am-1pm, one object) looks like one shape and two
// sessions that merely touch (2-3pm, then 3-4pm) look like two, with the
// gap between them being what shows that -- not an added border.
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

  const gridWidth = 7 * CELL_SIZE + 6 * GAP;
  const gridHeight = 24 * CELL_SIZE + 23 * GAP;

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

        <div style={{ position: "relative", width: gridWidth, height: gridHeight }}>
          {/* Interaction layer: an invisible cell per hour per day, purely
              for hit-testing drag/click -- always plain background, never
              colored by session state (that's the overlay's job). */}
          <div style={{ position: "absolute", inset: 0, display: "grid", gridTemplateColumns: `repeat(7, ${CELL_SIZE}px)`, gridTemplateRows: `repeat(24, ${CELL_SIZE}px)`, gap: GAP }}>
            {Array.from({ length: 24 }, (_, hour) =>
              DAY_LABELS.map((_, day) => {
                const session = sessionAt(sessions, day, hour);
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
                    style={{ width: CELL_SIZE, height: CELL_SIZE, borderRadius: 2, background: "color-mix(in srgb, var(--color-text) 8%, transparent)", cursor: "pointer" }}
                  />
                );
              })
            )}
          </div>

          {/* Visual layer: one real rectangle per session (plus the live
              drag preview), pointer-events disabled so clicks/drags pass
              straight through to the interaction layer underneath. */}
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
            {sessions.map((s) => {
              const r = spanRect(s.day, s.start, s.end);
              return <div key={s.id} style={{ position: "absolute", ...r, borderRadius: 3, background: "var(--color-accent)" }} />;
            })}
            {drag && (
              <div style={{ position: "absolute", ...spanRect(drag.day, drag.min, drag.max + 1), borderRadius: 3, background: "color-mix(in srgb, var(--color-accent) 45%, transparent)" }} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
