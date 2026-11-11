import { useEffect, useRef, useState } from "react";
import { formatFps } from "../../electron/cameras/frameRate.js";
import { useI18n } from "../i18n.jsx";

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
  ok: { tag: "tag-success", labelKey: "diag.verdict.ok" },
  slow: { tag: "tag-warning", labelKey: "diag.verdict.slow" },
  below: { tag: "tag-danger", labelKey: "diag.verdict.below" },
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

function formatDuration(minutes, t) {
  if (minutes == null) return "—";
  if (minutes < 60) return t("diag.minutes", { n: Math.round(minutes) });
  return t("diag.hours", { n: (minutes / 60).toFixed(1) });
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
  const { t } = useI18n();
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
      title={t("diag.upload.title")}
      action={
        <button className="btn btn-primary" style={{ fontSize: "var(--fs-fine)" }} disabled={status?.running} onClick={start}>
          {status?.running ? t("diag.upload.measuring") : result ? t("diag.upload.again") : t("diag.upload.measure")}
        </button>
      }
    >
      {status?.running ? (
        <>
          <Row
            label={
              status.sample > 1
                ? t("diag.upload.runningRun", { run: status.sample, total: status.sampleTotal })
                : t("diag.upload.running")
            }
            detail={t("diag.upload.runningDetail", { sent: formatBytes(status.sentBytes), total: formatBytes(status.totalBytes) })}
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
                <span className="text-3" style={{ fontSize: "var(--fs-body)" }}>{t("diag.upload.mbpsUp")}</span>
                {meta && <span className={`tag ${meta.tag}`}>{t(meta.labelKey)}</span>}
              </div>
              <div className="text-3" style={{ fontSize: "var(--fs-fine)" }}>
                {t("diag.upload.median", { n: result.samples.length, size: formatBytes(result.sizeBytes), samples: result.samples.map((m) => m.toFixed(1)).join(", ") })}
              </div>
            </div>
          </div>
          {result.unstable && (
            <Row
              label={t("diag.upload.unstable")}
              detail={t("diag.upload.unstableDetail", {
                slowest: result.slowest.toFixed(1),
                fastest: result.fastest.toFixed(1),
                fastTime: formatDuration(sessionMinutesAt(result.fastest, result.cameras), t),
                slowTime: formatDuration(result.slowestSessionMinutes, t),
              })}
              value={t("diag.upload.varies")}
              tone="warning"
            />
          )}
          <Row
            label={result.cameras === 1 ? t("diag.upload.session.one") : t("diag.upload.session.many", { n: result.cameras })}
            detail={
              result.verdict === "below"
                ? t("diag.upload.below")
                : result.verdict === "slow"
                  ? t("diag.upload.slow")
                  : t("diag.upload.good")
            }
            value={formatDuration(result.sessionMinutes, t)}
            tone={result.verdict === "below" ? "danger" : result.verdict === "slow" ? "warning" : "success"}
          />
        </>
      ) : status?.error ? (
        <Row label={t("diag.upload.failedTitle")} detail={status.error} value={t("diag.failed")} tone="danger" />
      ) : (
        <Row
          label={t("diag.upload.notYet")}
          detail={`${t("diag.upload.notYetDetail")}${
            cameraCount ? ` ${cameraCount === 1 ? t("diag.upload.assume.one") : t("diag.upload.assume.many", { n: cameraCount })}` : ""
          }`}
          value="—"
        />
      )}
    </Section>
  );
}

export default function DiagnosticsPage() {
  const { t } = useI18n();
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
        <div className="page-title">{t("diag.title")}</div>
        <button
          className="btn btn-secondary"
          style={{ marginLeft: "auto", fontSize: "var(--fs-fine)" }}
          disabled={running}
          onClick={run}
        >
          {running ? t("diag.checking") : t("diag.recheck")}
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
        <UploadSection cameraCount={cameras.length} />

        <Section title={t("diag.console.title")}>
          {checks?.console?.ok ? (
            <Row
              label={t("diag.console.reachable")}
              detail={checks.console.consoleUrl}
              value={`${checks.console.latencyMs} ms`}
              tone="success"
            />
          ) : (
            <Row
              label={t("diag.console.unreachable")}
              detail={checks?.console?.detail ?? t("diag.checking")}
              value={checks ? t("diag.failed") : "…"}
              tone={checks ? "danger" : undefined}
            />
          )}
        </Section>

        <Section title={t("diag.cameras.title")}>
          {!checks ? (
            <Row label={t("diag.checking")} value="…" />
          ) : cameras.length === 0 ? (
            <Row label={t("diag.cameras.none")} detail={t("diag.cameras.noneDetail")} value="—" />
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
                        c.fps ? `${formatFps(c.fps)} fps` : t("diag.cameras.fpsUnknown"),
                        c.bitrateKbps ? t("view.mbps", { n: (c.bitrateKbps / 1000).toFixed(1) }) : null,
                        c.fpsLevel === "blocked" ? t("diag.cameras.blocked") : null,
                        c.fpsLevel === "low" ? t("diag.cameras.low") : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                }
                value={
                  !c.reachable ? (c.isSampleClip ? t("state.missing") : t("state.offline"))
                  : c.fpsLevel === "blocked" ? t("ready.fpsBlocked")
                  : c.fpsLevel === "low" ? t("ready.fpsLow")
                  : c.isSampleClip ? t("ready.fileReady")
                  : t("state.ok")
                }
                tone={!c.reachable || c.fpsLevel === "blocked" ? "danger" : c.fpsLevel === "low" ? "warning" : "success"}
              />
            ))
          )}
        </Section>

        <Section title={t("diag.storage.title")}>
          {checks?.disk?.ok ? (
            <Row
              label={t("diag.storage.free")}
              detail={t("diag.storage.freeDetail", { path: checks.disk.path, hours: Math.round(checks.disk.recordingHours) })}
              value={formatBytes(checks.disk.freeBytes)}
              tone={checks.disk.recordingHours < 4 ? "danger" : checks.disk.recordingHours < 12 ? "warning" : "success"}
            />
          ) : (
            <Row label={t("diag.storage.failed")} detail={checks?.disk?.detail ?? t("diag.checking")} value={checks ? t("diag.failed") : "…"} />
          )}
        </Section>
      </div>
    </div>
  );
}
