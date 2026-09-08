import { useEffect, useRef, useState } from "react";

// The venue-survey page: is this site actually able to run a session?
//
// Written for the walkthrough someone does standing in a gym with a
// laptop, so every row answers in the terms of the thing that would go
// wrong -- "a 2-hour session would take 40 minutes to upload", not
// "8.4 Mbps" on its own. The measurement itself is electron/bandwidth.js
// (a real presigned PUT to R2, the same path a recording takes) and
// electron/diagnostics.js (console, cameras, disk).

const POLL_INTERVAL_MS = 500;

const VERDICT_META = {
  ok: { tag: "tag-success", label: "Good" },
  slow: { tag: "tag-warning", label: "Slow" },
  below: { tag: "tag-danger", label: "Too slow" },
};

function formatBytes(bytes) {
  if (bytes == null) return "—";
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${Math.round(bytes / 1e6)} MB`;
}

// Mirrors bandwidth.js's sessionUploadMinutes for the one case the main
// process doesn't precompute: the fastest sample's estimate.
const CAMERA_MBPS = 3;
function sessionMinutesAt(mbps, cameras) {
  return (CAMERA_MBPS * cameras * 2 * 3600) / mbps / 60;
}

function formatDuration(minutes) {
  if (minutes == null) return "—";
  if (minutes < 60) return `${Math.round(minutes)} minutes`;
  return `${(minutes / 60).toFixed(1)} hours`;
}

function Row({ label, value, tone, detail }) {
  return (
    <div className="row-line" style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: "var(--fs-strong)", fontWeight: 500 }}>{label}</div>
        {detail && (
          <div className="text-3" style={{ fontSize: "var(--fs-fine)", wordBreak: "break-word" }}>{detail}</div>
        )}
      </div>
      <span
        className="mono"
        style={{ flex: "none", fontSize: "var(--fs-body)", color: tone ? `var(--color-${tone})` : undefined }}
      >
        {value}
      </span>
    </div>
  );
}

function Section({ title, children, action }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div className="section-label section-label-quiet">{title}</div>
        {action && <div style={{ marginLeft: "auto" }}>{action}</div>}
      </div>
      <div className="card" style={{ padding: "2px 14px 8px" }}>{children}</div>
    </div>
  );
}

function UploadSection({ cameraCount }) {
  const [status, setStatus] = useState(null);
  const timer = useRef(null);

  const poll = () =>
    window.diagnosticsAPI?.bandwidthStatus().then((s) => {
      setStatus(s);
      return s;
    });

  useEffect(() => {
    poll();
    return () => clearInterval(timer.current);
  }, []);

  // Only polls while a test is actually running -- this page is otherwise
  // idle, and the status is a plain in-memory read in main.
  useEffect(() => {
    clearInterval(timer.current);
    if (status?.running) timer.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(timer.current);
  }, [status?.running]);

  const start = async () => {
    setStatus({ running: true, stage: "starting", sentBytes: 0, totalBytes: 0, result: null, error: null });
    await window.diagnosticsAPI?.startBandwidth();
    poll();
  };

  const result = status?.result;
  const meta = result ? VERDICT_META[result.verdict] : null;
  const pct = status?.totalBytes ? Math.min(100, (status.sentBytes / status.totalBytes) * 100) : 0;

  return (
    <Section
      title="Upload speed"
      action={
        <button className="btn btn-primary" style={{ fontSize: "var(--fs-fine)" }} disabled={status?.running} onClick={start}>
          {status?.running ? "Measuring…" : result ? "Measure again" : "Measure"}
        </button>
      }
    >
      {status?.running ? (
        <>
          <Row
            label={
              status.sample > 1
                ? `Uploading test data to the cloud (run ${status.sample} of ${status.sampleTotal})`
                : "Uploading test data to the cloud"
            }
            detail={`${formatBytes(status.sentBytes)} of ${formatBytes(status.totalBytes)} — repeated a few times, because the same connection can be several times slower one minute than the next`}
            value={`${Math.round(pct)}%`}
          />
          <div style={{ height: 4, borderRadius: 2, background: "var(--hairline)", margin: "4px 0 10px" }}>
            <div style={{ width: `${pct}%`, height: "100%", borderRadius: 2, background: "var(--color-accent)" }} />
          </div>
        </>
      ) : result ? (
        <>
          <div className="row-line" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="mono" style={{ fontSize: 22 }}>{result.mbps.toFixed(1)}</span>
                <span className="text-3" style={{ fontSize: "var(--fs-body)" }}>Mbps up</span>
                {meta && <span className={`tag ${meta.tag}`}>{meta.label}</span>}
              </div>
              <div className="text-3" style={{ fontSize: "var(--fs-fine)" }}>
                median of {result.samples.length} × {formatBytes(result.sizeBytes)} straight to the cloud storage
                recordings go to ({result.samples.map((m) => m.toFixed(1)).join(", ")} Mbps)
              </div>
            </div>
          </div>
          {result.unstable && (
            <Row
              label="The connection to cloud storage is inconsistent"
              detail={`Runs ranged from ${result.slowest.toFixed(1)} to ${result.fastest.toFixed(1)} Mbps minutes apart, so a session could take anywhere between ${formatDuration(
                sessionMinutesAt(result.fastest, result.cameras),
              )} and ${formatDuration(result.slowestSessionMinutes)}. Worth re-running at the venue's busiest hour before trusting either end.`}
              value="Varies"
              tone="warning"
            />
          )}
          <Row
            label={`A 2-hour session on ${result.cameras} camera${result.cameras === 1 ? "" : "s"}`}
            detail={
              result.verdict === "below"
                ? "Slower than the cameras record, so every session falls further behind — this venue needs a faster upload before it can run sessions back to back"
                : result.verdict === "slow"
                  ? "Reels will arrive well after everyone has left"
                  : "Comfortable — reels land while people are still around"
            }
            value={formatDuration(result.sessionMinutes)}
            tone={result.verdict === "below" ? "danger" : result.verdict === "slow" ? "warning" : "success"}
          />
        </>
      ) : status?.error ? (
        <Row label="Couldn't measure the upload speed" detail={status.error} value="Failed" tone="danger" />
      ) : (
        <Row
          label="Not measured yet"
          detail={`Uploads throwaway data to the cloud and times it. Nothing from your cameras is sent.${
            cameraCount ? ` Estimates assume ${cameraCount} camera${cameraCount === 1 ? "" : "s"} recording at once.` : ""
          }`}
          value="—"
        />
      )}
    </Section>
  );
}

export default function DiagnosticsPage() {
  const [checks, setChecks] = useState(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      setChecks(await window.diagnosticsAPI?.run());
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    run();
  }, []);

  const cameras = checks?.cameras ?? [];

  return (
    <div className="page-fixed">
      <div className="page-head">
        <div className="page-title">Diagnostics</div>
        <button
          className="btn btn-secondary"
          style={{ marginLeft: "auto", fontSize: "var(--fs-fine)" }}
          disabled={running}
          onClick={run}
        >
          {running ? "Checking…" : "Re-check"}
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
        <UploadSection cameraCount={cameras.length} />

        <Section title="Cloud console">
          {checks?.console?.ok ? (
            <Row
              label="Reachable"
              detail={checks.console.consoleUrl}
              value={`${checks.console.latencyMs} ms`}
              tone="success"
            />
          ) : (
            <Row
              label="Not reachable"
              detail={checks?.console?.detail ?? "Checking…"}
              value={checks ? "Failed" : "…"}
              tone={checks ? "danger" : undefined}
            />
          )}
        </Section>

        <Section title="Cameras">
          {!checks ? (
            <Row label="Checking…" value="…" />
          ) : cameras.length === 0 ? (
            <Row label="No cameras added yet" detail="Add one from the Cameras tab first" value="—" />
          ) : (
            cameras.map((c) => (
              <Row
                key={c.id}
                label={c.label}
                detail={
                  !c.reachable
                    ? c.detail
                    : [
                        c.width && c.height ? `${c.width}×${c.height}` : null,
                        c.fps ? `${c.fps.toFixed(0)} fps` : "frame rate unknown",
                        c.bitrateKbps ? `${(c.bitrateKbps / 1000).toFixed(1)} Mbps` : null,
                        c.fpsOk === false ? "below the 30 fps this pipeline needs" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                }
                value={!c.reachable ? "Offline" : c.fpsOk === false ? "Check fps" : "Online"}
                tone={!c.reachable ? "danger" : c.fpsOk === false ? "warning" : "success"}
              />
            ))
          )}
        </Section>

        <Section title="Storage">
          {checks?.disk?.ok ? (
            <Row
              label="Free space for recordings"
              detail={`${checks.disk.path} — about ${Math.round(checks.disk.recordingHours)} hours of recording from one camera`}
              value={formatBytes(checks.disk.freeBytes)}
              tone={checks.disk.recordingHours < 4 ? "danger" : checks.disk.recordingHours < 12 ? "warning" : "success"}
            />
          ) : (
            <Row label="Couldn't read free space" detail={checks?.disk?.detail ?? "Checking…"} value={checks ? "Failed" : "…"} />
          )}
        </Section>
      </div>
    </div>
  );
}
