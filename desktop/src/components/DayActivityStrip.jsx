const DAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

// Compact, read-only weekly-activity summary for one camera -- 7 bars, one
// per day, height proportional to how many of that day's 24 hours are
// scheduled active. Used on the Schedule overview page instead of a full
// WeekGrid thumbnail, which reads poorly at list-row size.
export default function DayActivityStrip({ cells, height = 28 }) {
  const set = cells instanceof Set ? cells : new Set(cells);
  const counts = DAY_LABELS.map((_, day) => {
    let n = 0;
    for (let h = 0; h < 24; h++) if (set.has(`${day}-${h}`)) n++;
    return n;
  });

  // The 0h floor (2px) and the smallest possible active value (1h) need to
  // be visibly different heights, not just different colors -- a linear
  // scale against the full 0-24 range compresses anything under ~6h to the
  // same rounded pixel height as 0h (caught by inspecting real rendered
  // heights, not just checking the color/title looked right).
  const barMax = height - 10; // leaves room for the day-letter label below
  const barHeight = (n) => (n === 0 ? 2 : Math.max(4, Math.round((n / 24) * barMax)));

  return (
    <div style={{ display: "inline-flex", alignItems: "flex-end", gap: 3, height }}>
      {counts.map((n, day) => (
        <div key={day} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, width: 10 }}>
          <div
            title={`${DAY_LABELS[day]}: ${n}h scheduled`}
            style={{
              width: 8,
              height: barHeight(n),
              borderRadius: 1.5,
              background: n > 0 ? "var(--color-accent)" : "color-mix(in srgb, var(--color-text) 10%, transparent)",
            }}
          />
          <span style={{ fontSize: 8, color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }}>{DAY_LABELS[day]}</span>
        </div>
      ))}
    </div>
  );
}
