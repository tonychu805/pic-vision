import { useEffect, useRef, useState } from "react";
import { cleanIpcError, describeAddFailure } from "../lib/ipcError.js";
import CameraCard from "../components/CameraCard.jsx";
import { buildCards } from "../lib/cameraView.js";
import { useI18n } from "../i18n.jsx";

const SCAN_TIMEOUT_MS = 5000;

// Rewritten after a plain-language walkthrough (2026-09-01, as a first-time
// venue owner with no technical background) found this form was the single
// biggest blocker in the app -- "ONVIF path" and a bare "Port" field with
// no explanation, no help finding an IP address, and identical copy
// whether or not we'd already found the device for them. Two real
// contexts now get different copy, and Port/path move behind "Advanced"
// since most people should never need them.
//
// Extended the same day with an RTSP fallback ladder, after a real camera
// on this network turned out to have a fully working video stream despite
// its ONVIF service being completely off (see store.js's addCameraViaRtsp
// for the full reasoning): when the ONVIF attempt fails, this
// automatically tries a short generic list of common stream paths before
// giving up, and offers a raw-RTSP-URL field as the true last resort --
// each step vendor-neutral, none of it branching on a detected brand.
function ManualAddDialog({ initialHostname = "", initialVendor = null, initialPort = 80, onClose, onAdded }) {
  const { t, rich } = useI18n();
  const foundIt = Boolean(initialHostname);
  // "Sample clip" (2026-09-03): a local video file stands in for a live
  // camera, so calibration and the cloud pipeline can be exercised
  // without a real, court-facing camera -- neither one on this network
  // has reliably been that. Only offered on a genuine "Add manually" open
  // (foundIt=false); a prefilled discovered-device card is already known
  // to be a real camera.
  const [sourceType, setSourceType] = useState("camera");
  const [form, setForm] = useState({ label: "", hostname: initialHostname, port: initialPort, path: "", username: "", password: "" });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // 'form' -> trying ONVIF | 'tryingRtsp' -> auto-probing common stream
  // paths | 'rtspUrl' -> ONVIF and the auto-probe both failed, offer a
  // raw-URL field as the last resort.
  const [phase, setPhase] = useState("form");
  const [rtspUrl, setRtspUrl] = useState("");
  const [subRtspUrl, setSubRtspUrl] = useState("");
  // Which attempt `error` belongs to. Without this the ONVIF failure would
  // be reprinted under the stream-URL field as though the operator's own
  // URL had just been rejected, before they had typed anything.
  const [urlAttempted, setUrlAttempted] = useState(false);
  // The plain-language reason classifyProbeError gave for 'certWarning' --
  // kept separate from `error` so it survives into the decline path, which
  // needs it even after `error` has been reused for the RTSP ladder's own
  // failure.
  const [certDetail, setCertDetail] = useState("");
  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const [clipLabel, setClipLabel] = useState("");
  const [clipPath, setClipPath] = useState("");
  const [clipError, setClipError] = useState("");
  const [clipSaving, setClipSaving] = useState(false);

  // Real bug found 2026-09-03: with no try/catch here, a main-process
  // change that hadn't taken effect yet (preload.cjs only reloads on a
  // full app restart, not Vite's renderer hot-reload -- see
  // desktop/README.md's own note on this exact class of bug) made
  // `window.systemAPI.pickVideoFile` undefined, and calling it threw
  // inside this async function with nothing catching the rejection --
  // the button looked like it silently did nothing. Caught this specific
  // case explicitly so it says so instead of failing invisibly.
  const pickClipFile = async () => {
    setClipError("");
    if (typeof window.systemAPI?.pickVideoFile !== "function") {
      setClipError(t("add.clip.notLoaded"));
      return;
    }
    try {
      const picked = await window.systemAPI.pickVideoFile();
      if (picked) setClipPath(picked);
    } catch (err) {
      setClipError(cleanIpcError(err));
    }
  };

  const submitSampleClip = async (e) => {
    e.preventDefault();
    if (!clipPath) return;
    setClipSaving(true);
    setClipError("");
    try {
      onAdded(await window.cameraAPI.addSampleClip({ label: clipLabel, filePath: clipPath }));
    } catch (err) {
      setClipError(cleanIpcError(err));
      setClipSaving(false);
    }
  };

  // Before giving up on ONVIF entirely, see if the camera has a real video
  // stream anyway (a real case this session: ONVIF was completely switched
  // off, but the stream itself worked the whole time at a common, guessable
  // path). Shared by the ONVIF attempt's own failure and by declining the
  // certificate prompt below -- both land here the same way.
  const fallBackToRtspLadder = async (failureError) => {
    setPhase("tryingRtsp");
    try {
      const found = await window.cameraAPI.probeRtspFallback({
        hostname: form.hostname,
        username: form.username,
        password: form.password,
      });
      if (found) {
        const camera = await window.cameraAPI.addRtsp({
          label: form.label,
          hostname: form.hostname,
          port: 554,
          path: found.path,
          username: form.username,
          password: form.password,
        });
        onAdded(camera);
        return;
      }
    } catch {
      // fall through to the manual RTSP-URL offer below
    }
    setPhase("rtspUrl");
    setError(failureError);
    setSaving(false);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const camera = await window.cameraAPI.add({ ...form, port: Number(form.port) || 80 });
      // A resolved value, not a thrown one -- cameras:add only takes this
      // shape for the one state that needs a real decision rather than a
      // fallback (main.js's handler).
      if (camera?.untrustedCert) {
        setCertDetail(camera.detail);
        setPhase("certWarning");
        setSaving(false);
        return;
      }
      onAdded(camera);
    } catch (onvifErr) {
      await fallBackToRtspLadder(onvifErr);
    }
  };

  const acceptCert = async () => {
    setSaving(true);
    setError("");
    try {
      const camera = await window.cameraAPI.add({ ...form, port: Number(form.port) || 80, acceptUnverifiedCert: true });
      onAdded(camera);
    } catch (err) {
      // Rare -- the operator already said yes to the certificate, so a
      // failure here is something else entirely. Same ladder as any other
      // ONVIF failure.
      await fallBackToRtspLadder(err);
    }
  };

  const declineCert = () => {
    fallBackToRtspLadder(new Error(certDetail));
  };

  const submitRtspUrl = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const parsed = await window.cameraAPI.parseRtspUrl(rtspUrl, form.username, form.password);
      // A malformed secondary URL degrades to "no sub-stream", same as an
      // unreachable one -- it must not block adding the camera on its
      // already-verified primary URL.
      let subParsed = null;
      if (subRtspUrl) {
        try {
          subParsed = await window.cameraAPI.parseRtspUrl(subRtspUrl, form.username, form.password);
        } catch {
          subParsed = null;
        }
      }
      const camera = await window.cameraAPI.addRtsp({ label: form.label, ...parsed, sub: subParsed });
      onAdded(camera);
    } catch (err) {
      setError(err);
      setUrlAttempted(true);
      setSaving(false);
    }
  };

  if (phase === "certWarning") {
    return (
      <div className="dialog-backdrop">
        <div className="dialog">
          <div className="dialog-title">{t("add.cert.title")}</div>
          <div className="dialog-body">
            {t("add.cert.body", { detail: cleanIpcError(certDetail, t) })}
          </div>
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={declineCert} disabled={saving}>
              {t("add.cert.useRtsp")}
            </button>
            <button type="button" className="btn btn-primary" onClick={acceptCert} disabled={saving}>
              {saving ? t("add.connecting") : t("add.cert.trust")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "tryingRtsp") {
    return (
      <div className="dialog-backdrop">
        <div className="dialog">
          <div className="dialog-title">{t("add.looking.title")}</div>
          <div className="dialog-body">
            {t("add.looking.body")}
          </div>
        </div>
      </div>
    );
  }

  // Only rendered on a genuine "Add manually" open (foundIt=false) --
  // switching source type wouldn't make sense once a real device is
  // already known (a discovered card, or the RTSP-fallback phases below).
  const sourceSelector = !foundIt && (
    <div className="field">
      <label>{t("add.source.label")}</label>
      <select className="input" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
        <option value="camera">{t("add.source.camera")}</option>
        <option value="sampleClip">{t("add.source.clip")}</option>
      </select>
    </div>
  );

  if (sourceType === "sampleClip" && !foundIt) {
    return (
      <div className="dialog-backdrop">
        <form className="dialog" onSubmit={submitSampleClip}>
          <div className="dialog-title">{t("add.clip.title")}</div>
          {sourceSelector}
          <div className="dialog-body">
            {t("add.clip.body")}
          </div>
          <div className="field">
            <label>{t("add.nameOptional")}</label>
            <input className="input" value={clipLabel} onChange={(e) => setClipLabel(e.target.value)} placeholder={t("add.clip.namePlaceholder")} />
          </div>
          <div className="field">
            <label>{t("add.clip.file")}</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button type="button" className="btn btn-secondary" onClick={pickClipFile}>{t("add.clip.choose")}</button>
              <span style={{ fontSize: "var(--fs-body)", fontFamily: "var(--font-mono)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {clipPath || t("add.clip.noFile")}
              </span>
            </div>
          </div>
          {clipError && (
            <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: 0 }}>{clipError}</p>
          )}
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary" disabled={clipSaving || !clipPath}>
              {clipSaving ? t("add.adding") : t("add.add")}
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (phase === "rtspUrl") {
    // `error` here is whatever the ONVIF attempt threw, until the operator
    // submits a stream URL of their own -- after which it's that attempt's
    // failure instead, and no longer says anything about ONVIF.
    const failure = describeAddFailure(error, form.hostname, t);
    const urlError = urlAttempted ? error : null;
    return (
      <div className="dialog-backdrop">
        <form className="dialog" onSubmit={submitRtspUrl}>
          <div className="dialog-title">{failure.title}</div>
          <div className="dialog-body">{failure.body}</div>
          <div className="field">
            <label>{t("add.url.label")}</label>
            <input
              className="input"
              value={rtspUrl}
              onChange={(e) => { setRtspUrl(e.target.value); if (urlAttempted) { setUrlAttempted(false); setError(""); } }}
              placeholder="rtsp://192.168.1.42:554/..."
              required
              autoFocus
            />
          </div>
          <div className="field">
            <label>{t("add.sub.label")}</label>
            <input
              className="input"
              value={subRtspUrl}
              onChange={(e) => setSubRtspUrl(e.target.value)}
              placeholder="rtsp://192.168.1.42:554/..."
            />
          </div>
          {urlError && (
            <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: 0 }}>
              {t("add.url.failed", { reason: cleanIpcError(urlError) })}
            </p>
          )}
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? t("add.connecting") : t("add.connectAdd")}</button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog" onSubmit={submit}>
        <div className="dialog-title">{foundIt ? t("add.form.titleFound") : t("add.form.titleManual")}</div>
        {sourceSelector}
        <div className="dialog-body">
          {foundIt ? (
            <>
              {initialVendor ? t("add.form.foundVendor", { vendor: initialVendor }) : t("add.form.found")}
            </>
          ) : (
            <>
              {rich("add.form.manual", { example: <span style={{ fontFamily: "var(--font-mono)" }}>192.168.1.42</span> })}
            </>
          )}
        </div>
        <div className="field"><label>{t("add.nameOptional")}</label><input className="input" value={form.label} onChange={update("label")} placeholder={t("add.form.namePlaceholder")} /></div>
        <div className="field">
          <label>{t("add.form.ip")}</label>
          <input className="input" value={form.hostname} onChange={update("hostname")} required autoFocus={!foundIt} />
        </div>
        <div className="field"><label>{t("add.form.username")}</label><input className="input" value={form.username} onChange={update("username")} autoFocus={foundIt} /></div>
        <div className="field"><label>{t("add.form.password")}</label><input className="input" type="password" value={form.password} onChange={update("password")} /></div>

        {!showAdvanced ? (
          <button
            type="button"
            className="btn btn-ghost"
            style={{ alignSelf: "flex-start", fontSize: "var(--fs-body)", padding: 0 }}
            onClick={() => setShowAdvanced(true)}
          >
            {t("add.form.advanced")}
          </button>
        ) : (
          <div style={{ display: "flex", gap: 10 }}>
            <div className="field" style={{ flex: 1 }}><label>{t("add.form.port")}</label><input className="input" type="number" value={form.port} onChange={update("port")} /></div>
            <div className="field" style={{ flex: 2 }}>
              <label>{t("add.form.path")}</label>
              <input className="input" value={form.path} onChange={update("path")} placeholder="/onvif/device_service" />
            </div>
          </div>
        )}

        {error && (
          <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: 0 }}>
            {t("add.form.failed", { error })}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? t("add.connecting") : t("add.connectAdd")}</button>
        </div>
      </form>
    </div>
  );
}

export default function CamerasPage({ onOpenCamera, onCameraCountChange, onOpenScanSettings, active }) {
  const { t } = useI18n();
  const [configured, setConfigured] = useState([]);
  const [discovered, setDiscovered] = useState([]);
  const [sweepHits, setSweepHits] = useState([]);
  const [statusById, setStatusById] = useState({});
  const [scanning, setScanning] = useState(false);
  const [scanPct, setScanPct] = useState(0);
  const [hasScanned, setHasScanned] = useState(false);
  const [scanError, setScanError] = useState(null);
  const [sweepError, setSweepError] = useState(null);
  // Why an empty scan was empty (electron/cameras/networkPresence.js).
  // Null until a completed scan finds nothing; `diagnosing` covers the few
  // seconds it takes, so the empty state doesn't flash the generic text
  // and then replace it.
  const [scanVerdict, setScanVerdict] = useState(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [picked, setPicked] = useState(new Set());
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPrefill, setManualPrefill] = useState({ hostname: "", vendor: null, port: 80 });
  const [bulkOpen, setBulkOpen] = useState(false);
  const scanTimer = useRef(null);
  // Bumped by every scan start and by Stop. The discover/sweep promises
  // can't be aborted (no AbortSignal through the preload bridge), so Stop
  // used to only hide the progress bar -- the awaited results still landed
  // a few seconds later and repopulated the list, which is not what a
  // button labelled Stop should do. Results now carry the run they belong
  // to and a stale one is dropped on arrival.
  const scanRun = useRef(0);

  // Bulk select (Sign in / Sync time / Update firmware) isn't wired up
  // to anything real yet -- see the "aren't wired up yet" dialog below.
  // Gated behind a PostHog feature flag rather than deleted, so it can
  // be turned on later without a code deploy once it's built. Fails
  // closed: defaults to hidden until the flag resolves true.
  const [selectFeatureEnabled, setSelectFeatureEnabled] = useState(false);
  useEffect(() => {
    window.analyticsAPI?.isFeatureEnabled("desktop-camera-bulk-select").then(setSelectFeatureEnabled);
  }, []);

  // Keyed by camera id, not hostname -- a sample-clip camera (2026-09-03)
  // has no hostname at all, and two of them would otherwise collide under
  // the same `undefined` key and show each other's status.
  const refreshConfigured = async () => {
    const cameras = await window.cameraAPI.list();
    setConfigured(cameras);
    for (const camera of cameras) {
      setStatusById((s) => ({ ...s, [camera.id]: "checking" }));
      // The handler classifies the failure and never throws, so the state
      // says WHY. This used to be `.catch(() => "offline")`, which threw
      // the error away and rendered "Not answering" for a camera that had
      // answered "401 Unauthorized" -- sending the operator to check
      // cables when the fix was a password (reported 2026-09-07).
      //
      // The catch below is now only for the IPC call itself failing (a
      // stale preload, main process gone), not for the camera.
      window.cameraAPI
        .testConnection(camera)
        .then((result) => setStatusById((s) => ({ ...s, [camera.id]: result.state ?? "offline" })))
        .catch(() => setStatusById((s) => ({ ...s, [camera.id]: "offline" })));
    }
  };

  // No automatic network scan on mount (operator's call, 2026-09-03,
  // reversing the auto-scan-on-start behavior this page had before) --
  // `startScan` now only ever runs from an explicit "Scan"/"Scan again"
  // click. `refreshConfigured` still runs on mount and every time this
  // tab becomes active again -- that's just a cheap local-store read
  // (already-configured cameras + a connection-status check for each),
  // not a real network scan, and it needs to catch a camera renamed or
  // removed from its own detail page while this tab was hidden.
  useEffect(() => {
    if (active) refreshConfigured();
  }, [active]);

  // Keeps each card's readiness current -- a recording the console started,
  // a calibration that just finished -- while this tab is open. Re-reads the
  // list only: no camera is contacted, unlike refreshConfigured above.
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => { window.cameraAPI.list().then(setConfigured).catch(() => {}); }, 10_000);
    return () => clearInterval(id);
  }, [active]);

  const startScan = async () => {
    const run = ++scanRun.current;
    setScanning(true);
    setScanError(null);
    setSweepError(null);
    setScanVerdict(null);
    setScanPct(4);
    const start = Date.now();
    scanTimer.current = setInterval(() => {
      setScanPct(Math.min(96, ((Date.now() - start) / SCAN_TIMEOUT_MS) * 100));
    }, 120);

    // Run both discovery methods together: WS-Discovery only finds
    // cameras that choose to answer it (electron/cameras/discovery.js);
    // the port sweep (electron/cameras/networkSweep.js) finds anything
    // with RTSP open regardless of whether it cooperates with discovery
    // protocols -- built 2026-09-01 after a real camera on this network
    // did the latter and not the former.
    // sweep() takes no options anymore -- Scan settings (extra ranges,
    // per-address timeout) is the single source of truth main.js's own
    // handler reads internally, same as it already does for the
    // auto-detected network range.
    const [discoverResult, sweepResult] = await Promise.allSettled([
      window.cameraAPI.discover({ timeout: SCAN_TIMEOUT_MS }),
      window.cameraAPI.sweep(),
    ]);

    if (run !== scanRun.current) return; // stopped while these were in flight

    if (discoverResult.status === "fulfilled") setDiscovered(discoverResult.value);
    else setScanError(discoverResult.reason?.message ?? String(discoverResult.reason));

    if (sweepResult.status === "fulfilled") setSweepHits(sweepResult.value);
    else setSweepError(sweepResult.reason?.message ?? String(sweepResult.reason));

    clearInterval(scanTimer.current);
    setScanPct(100);
    setHasScanned(true);
    setTimeout(() => setScanning(false), 200);

    // Only when the sweep actually COMPLETED and still found nothing, and
    // only when there's an empty page to explain. A sweep that errored has
    // no standing to say anything about the network -- that case already
    // renders its own message -- and an operator who has cameras set up
    // isn't looking at the empty state at all.
    const foundNothing =
      (discoverResult.value?.length ?? 0) + (sweepResult.value?.length ?? 0) === 0;
    if (sweepResult.status !== "fulfilled" || !foundNothing || configured.length > 0) return;

    setDiagnosing(true);
    try {
      const verdict = await window.cameraAPI.explainEmptyScan();
      if (run === scanRun.current) setScanVerdict(verdict);
    } catch {
      // Falls back to the generic wording. An explanation that can't be
      // produced is not worth an error of its own -- the operator's actual
      // problem is still "nothing was found".
    } finally {
      if (run === scanRun.current) setDiagnosing(false);
    }
  };

  const stopScan = () => {
    scanRun.current += 1;
    clearInterval(scanTimer.current);
    setScanning(false);
    setDiagnosing(false);
  };

  useEffect(() => () => clearInterval(scanTimer.current), []);

  const cards = buildCards({ configured, discovered, sweepHits, statusById }, t);
  // Used to also require `hasScanned === false`, which meant a scan that
  // found nothing fell through to the list branch and rendered an empty
  // scroll area -- a header and blank space, at exactly the moment there's
  // most to explain. Both cases show the empty state now; only the wording
  // differs.
  const isEmpty = !scanning && cards.length === 0;
  // An isolating network is a different problem from an empty one, and
  // looks like one before the text is read.
  const emptyIcon =
    scanVerdict?.state === "isolated"
      ? "ph ph-wifi-slash"
      : hasScanned
        ? "ph ph-binoculars"
        : "ph ph-radar";
  const mine = cards.filter((c) => c.kind === "configured");
  const found = cards.filter((c) => c.kind !== "configured");

  useEffect(() => {
    onCameraCountChange?.(cards.length);
  }, [cards.length]);

  const togglePick = (key) => setPicked((p) => { const next = new Set(p); next.has(key) ? next.delete(key) : next.add(key); return next; });

  const openManual = (hostname = "", vendor = null, port = 80) => {
    setManualPrefill({ hostname, vendor, port });
    setManualOpen(true);
  };

  // One workflow for every not-yet-configured card, regardless of how it
  // was found (operator's call, 2026-09-01: signing in to a WS-Discovery
  // hit used to open a separate, simpler inline form on a detail page --
  // ONVIF-only, no fallback if it failed -- while a sweep hit opened this
  // fuller dialog with the RTSP fallback ladder. Different capability
  // depending on discovery method wasn't a deliberate distinction worth
  // keeping, so both now open the same dialog.
  const handleCardOpen = (card) => {
    if (selectMode) return togglePick(card.key);
    if (card.kind === "configured") return onOpenCamera(card);
    // `device.port` means two different things depending on how the card
    // was found -- a WS-Discovery hit's is the real ONVIF port (e.g. a
    // Tapo C200's 2020, worth pre-filling instead of a possibly-wrong 80),
    // but a sweep hit's is the RTSP port it was found on (554), which is
    // NOT an ONVIF port. Passing that through as the dialog's ONVIF-
    // connect port was a real bug found right after shipping it: the
    // initial ONVIF attempt then tried an HTTP/SOAP request against a
    // raw RTSP port and hung indefinitely (a stuck "Connecting…") instead
    // of failing fast the way a real wrong-port HTTP request does --
    // reproduced live on the Synology BC510, which used to fail over to
    // the RTSP ladder in about a second.
    const onvifPort = card.kind === "discovered" ? card.device.port ?? 80 : 80;
    return openManual(card.device.hostname, card.device.vendor, onvifPort);
  };

  // Removes a not-yet-configured card from this scan's results without
  // requiring the operator to sign in first (a real request, 2026-09-01
  // -- "even before signing in, i should still be able to delete a
  // detected camera," e.g. a device that turns out not to be theirs at
  // all). Session-local, not persisted anywhere: the device is still
  // really on the network, so it can reappear on the next "Scan again"
  // -- there's nothing to un-discover, only a card to hide for now.
  const dismissDevice = (hostname) => {
    setDiscovered((d) => d.filter((device) => device.hostname !== hostname));
    setSweepHits((s) => s.filter((device) => device.hostname !== hostname));
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 12, padding: "16px 22px 12px" }}>
        <div style={{ minWidth: 0 }}>
          {/* The title used to become the count ("3 cameras") and the
              state ("Looking for cameras"), so the page changed identity
              as you used it and the sidebar's own count said it again.
              Constant title, changing subtitle. */}
          <div className="page-title">{t("cams.title")}</div>
          <div className="page-sub">
            {scanning
              ? t("cams.sub.scanning")
              : mine.length === 0 && found.length === 0
                ? t("cams.sub.none")
                // A scan that turns up only cameras already added used to
                // leave this line reading exactly as it did before the
                // click, so there was no way to tell the scan had run at
                // all (PIC-152). Say what happened until something changes.
                : hasScanned && found.length === 0
                  ? t("cams.sub.scanDoneNothing", { n: mine.length })
                  : found.length
                    ? t("cams.sub.addedFound", { n: mine.length, found: found.length })
                    : t("cams.sub.added", { n: mine.length })}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          {selectFeatureEnabled && (
            <button className="btn btn-secondary" onClick={() => setSelectMode((v) => !v)}>
              <i className="ph ph-check-square-offset" style={{ fontSize: 15 }} />{t("cams.select")}
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => openManual()}>
            <i className="ph ph-plus" style={{ fontSize: 15 }} />{t("cams.addManually")}
          </button>
          <button className="btn btn-primary" onClick={startScan} disabled={scanning}>
            <i className="ph ph-radar" style={{ fontSize: 16 }} />{scanning ? t("cams.scanning") : t("cams.scan")}
          </button>
          {/* Scan settings used to be a top-level nav tab, a peer of
              Cameras/Log/Cloud console -- odd standing for a page whose
              only job is to configure this one button. It lives behind
              this instead, next to the thing it affects. */}
          <button
            className="btn btn-ghost"
            style={{ padding: "0 6px" }}
            title={t("cams.scanOptions")}
            aria-label={t("cams.scanOptions")}
            onClick={onOpenScanSettings}
          >
            <i className="ph ph-sliders-horizontal" style={{ fontSize: 16 }} />
          </button>
        </div>
      </div>

      {scanning && (
        <div style={{ flex: "none", margin: "0 22px 14px", padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: "var(--fs-body)", fontWeight: 500 }}>{t("cams.scanning.panel")}</span>
            <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: "var(--fs-body)" }} onClick={stopScan}>{t("cams.stop")}</button>
          </div>
          <div style={{ height: 3, borderRadius: 2, background: "color-mix(in srgb, var(--color-text) 10%, transparent)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${scanPct}%`, background: "var(--color-accent)", transition: "width .12s linear" }} />
          </div>
        </div>
      )}

      {/* WS-Discovery multicast is often unavailable on managed Wi-Fi and
          some macOS network configurations.  The RTSP sweep is deliberately
          an independent fallback, so one method failing does not mean the
          scan failed.  Only call this a problem when neither produced a
          result. */}
      {scanError && sweepError && (
        <p style={{ margin: "0 22px 12px", fontSize: "var(--fs-body)", color: "var(--color-danger)" }}>
          {t("cams.scanProblem")}
        </p>
      )}

      {selectMode && (
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, margin: "0 22px 12px", padding: "8px 14px", borderRadius: "var(--radius-md)", background: "var(--color-accent-900)" }}>
          <span style={{ fontSize: "var(--fs-body)", fontWeight: 500, color: "var(--color-accent-200)" }}>{t("cams.selected", { n: picked.size, total: cards.length })}</span>
          <div style={{ width: 1, height: 14, background: "var(--color-accent-700)" }} />
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-key" style={{ fontSize: 14 }} />{t("cams.bulk.signIn")}</button>
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-clock-clockwise" style={{ fontSize: 14 }} />{t("cams.bulk.syncTime")}</button>
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-arrow-circle-up" style={{ fontSize: 14 }} />{t("cams.bulk.firmware")}</button>
          <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: "var(--fs-body)", color: "var(--text-3)" }} onClick={() => { setSelectMode(false); setPicked(new Set()); }}>{t("cams.done")}</button>
        </div>
      )}

      {isEmpty ? (
        <div style={{ flex: 1, display: "grid", placeItems: "center", padding: "0 22px 40px" }}>
          <div style={{ maxWidth: 420, textAlign: "center" }}>
            <div style={{ width: 104, height: 104, margin: "0 auto 18px", borderRadius: "50%", display: "grid", placeItems: "center", background: "radial-gradient(circle, var(--color-accent-900), transparent 70%)" }}>
              <i className={emptyIcon} style={{ fontSize: 44, color: "var(--color-accent)" }} />
            </div>
            <div style={{ fontFamily: "var(--font-heading)", fontSize: 22, marginBottom: 6 }}>
              {/* The verdict's own headline when there is one. "Nothing
                  found on this network" is true of all four situations
                  networkPresence.js separates, which is why it was no help
                  at the venue this was built for (2026-09-19). */}
              {scanVerdict?.title ?? (hasScanned ? t("cams.empty.nothingFound") : t("cams.empty.none"))}
            </div>
            <p className="text-2" style={{ fontSize: "var(--fs-strong)", lineHeight: 1.6 }}>
              {scanVerdict?.detail ?? (diagnosing ? (
                t("cams.empty.diagnosing")
              ) : hasScanned ? (
                t("cams.empty.scannedNone")
              ) : (
                t("cams.empty.intro")
              ))}
            </p>
            {/* The numbers the paragraph above is a reading of, so the
                reading can be checked rather than taken on faith. */}
            {scanVerdict?.facts?.cidr && (
              <div className="text-3" style={{ fontSize: "var(--fs-body)", marginTop: 10 }}>
                {t("cams.empty.facts", {
                  cidr: scanVerdict.facts.cidr,
                  checked: scanVerdict.facts.addressesChecked,
                  devices: scanVerdict.facts.neighbors === 1 ? t("cams.empty.oneDevice") : t("cams.empty.manyDevices", { n: scanVerdict.facts.neighbors }),
                })}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
              <button className="btn btn-primary" onClick={startScan}>
                <i className="ph ph-radar" style={{ fontSize: 16 }} />{hasScanned ? t("cams.scanAgain") : t("cams.scanThisNetwork")}
              </button>
              <button className="btn btn-secondary" onClick={() => openManual()}>{t("cams.addManually")}</button>
            </div>
            {hasScanned && (
              <button className="btn btn-ghost" style={{ marginTop: 10, fontSize: "var(--fs-body)" }} onClick={onOpenScanSettings}>
                {t("cams.checkScanOptions")}
              </button>
            )}
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 22px 22px" }}>
          {/* Two sections, not one flat list (2026-09-06): a camera you
              set up and an unconfirmed open port that might not be a
              camera at all were rendering identically, with only a
              sentence above the list to tell them apart. buildCards
              already returns them in this order -- this just makes the
              boundary visible. */}
          {mine.length > 0 && (
            <>
              {found.length > 0 && <div className="section-label">{t("cams.section.yours")}</div>}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {mine.map((card) => (
                  <CameraCard key={card.key} card={card} selectMode={selectMode} picked={picked.has(card.key)} onOpen={() => handleCardOpen(card)} onDismiss={() => dismissDevice(card.key)} />
                ))}
              </div>
            </>
          )}

          {found.length > 0 && (
            <>
              <div className="section-label" style={{ marginTop: mine.length > 0 ? 20 : 0 }}>
                {t("cams.section.found")}
              </div>
              <p className="page-sub" style={{ margin: "-6px 0 8px" }}>
                {found.length === 1 ? t("cams.found.one") : t("cams.found.many", { n: found.length })}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, opacity: 0.92 }}>
                {found.map((card) => (
                  <CameraCard key={card.key} card={card} selectMode={selectMode} picked={picked.has(card.key)} onOpen={() => handleCardOpen(card)} onDismiss={() => dismissDevice(card.key)} />
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {manualOpen && (
        <ManualAddDialog
          initialHostname={manualPrefill.hostname}
          initialVendor={manualPrefill.vendor}
          initialPort={manualPrefill.port}
          onClose={() => setManualOpen(false)}
          onAdded={() => { setManualOpen(false); refreshConfigured(); }}
        />
      )}

      {bulkOpen && (
        <div className="dialog-backdrop">
          <div className="dialog" style={{ width: "min(520px, 100%)" }}>
            <div className="dialog-title">{picked.size === 1 ? t("cams.bulk.title.one") : t("cams.bulk.title.many", { n: picked.size })}</div>
            <div className="dialog-body">
              {t("cams.bulk.body")}
            </div>
            <div className="dialog-actions">
              <button className="btn btn-secondary" onClick={() => setBulkOpen(false)}>{t("cams.close")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
