import { useEffect, useRef, useState } from "react";
import CameraCard from "../components/CameraCard.jsx";
import { buildCards } from "../lib/cameraView.js";

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
      setClipError("This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).");
      return;
    }
    try {
      const picked = await window.systemAPI.pickVideoFile();
      if (picked) setClipPath(picked);
    } catch (err) {
      setClipError(err.message);
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
      setClipError(err.message);
      setClipSaving(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const camera = await window.cameraAPI.add({ ...form, port: Number(form.port) || 80 });
      onAdded(camera);
      return;
    } catch (onvifErr) {
      // ONVIF failed -- before giving up, see if the camera has a real
      // video stream anyway (a real case this session: ONVIF was
      // completely switched off, but the stream itself worked the whole
      // time at a common, guessable path).
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
      setError(onvifErr.message);
      setSaving(false);
    }
  };

  const submitRtspUrl = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const parsed = await window.cameraAPI.parseRtspUrl(rtspUrl, form.username, form.password);
      const camera = await window.cameraAPI.addRtsp({ label: form.label, ...parsed });
      onAdded(camera);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  if (phase === "tryingRtsp") {
    return (
      <div className="dialog-backdrop">
        <div className="dialog">
          <div className="dialog-title">Looking for a video stream…</div>
          <div className="dialog-body">
            Sign-in didn't work the usual way — checking whether this camera has a video stream available directly.
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
      <label>Add</label>
      <select className="input" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
        <option value="camera">A live camera</option>
        <option value="sampleClip">A sample clip (for testing)</option>
      </select>
    </div>
  );

  if (sourceType === "sampleClip" && !foundIt) {
    return (
      <div className="dialog-backdrop">
        <form className="dialog" onSubmit={submitSampleClip}>
          <div className="dialog-title">Add a sample clip</div>
          {sourceSelector}
          <div className="dialog-body">
            Upload a video file to test calibration and the cloud pipeline without a real camera — it's treated
            like a camera whose one recording is this file.
          </div>
          <div className="field">
            <label>Name (optional)</label>
            <input className="input" value={clipLabel} onChange={(e) => setClipLabel(e.target.value)} placeholder="Test clip" />
          </div>
          <div className="field">
            <label>Video file</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button type="button" className="btn btn-secondary" onClick={pickClipFile}>Choose file…</button>
              <span style={{ fontSize: 12.5, fontFamily: "ui-monospace, Menlo, monospace", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {clipPath || "No file chosen"}
              </span>
            </div>
          </div>
          {clipError && (
            <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: 0 }}>{clipError}</p>
          )}
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={clipSaving || !clipPath}>
              {clipSaving ? "Adding…" : "Add"}
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (phase === "rtspUrl") {
    return (
      <div className="dialog-backdrop">
        <form className="dialog" onSubmit={submitRtspUrl}>
          <div className="dialog-title">Couldn't connect automatically</div>
          <div className="dialog-body">
            This camera might have ONVIF turned off — check its own app or settings for a network option called
            "ONVIF" and make sure it's turned on, then try again above. In the meantime, if your camera's app shows
            you a video stream address (sometimes called an "RTSP URL" or "stream URL"), you can paste it here to
            add it directly.
          </div>
          <div className="field">
            <label>Video stream address</label>
            <input
              className="input"
              value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
              placeholder="rtsp://192.168.1.42:554/..."
              required
              autoFocus
            />
          </div>
          {error && (
            <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: 0 }}>
              Couldn't connect with that either. ({error})
            </p>
          )}
          <div className="dialog-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Connecting…" : "Connect & add"}</button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog" onSubmit={submit}>
        <div className="dialog-title">{foundIt ? "Set up this camera" : "Add a camera by IP address"}</div>
        {sourceSelector}
        <div className="dialog-body">
          {foundIt ? (
            <>
              We found {initialVendor ? `a ${initialVendor} device` : "a device"} on your network. Enter its sign-in
              below to connect it — the same username and password you'd use in the camera's own app, not your
              Wi-Fi password.
            </>
          ) : (
            <>
              Don't see your camera in the list? You can add it directly if you know its IP address — check the
              camera's own app, usually under Network or Wi-Fi settings. It looks like a short string of numbers,
              e.g. <span style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>192.168.1.42</span>.
            </>
          )}
        </div>
        <div className="field"><label>Name (optional)</label><input className="input" value={form.label} onChange={update("label")} placeholder="Court 1 camera" /></div>
        <div className="field">
          <label>Camera IP address</label>
          <input className="input" value={form.hostname} onChange={update("hostname")} required autoFocus={!foundIt} />
        </div>
        <div className="field"><label>Username</label><input className="input" value={form.username} onChange={update("username")} autoFocus={foundIt} /></div>
        <div className="field"><label>Password</label><input className="input" type="password" value={form.password} onChange={update("password")} /></div>

        {!showAdvanced ? (
          <button
            type="button"
            className="btn btn-ghost"
            style={{ alignSelf: "flex-start", fontSize: 12.5, padding: 0 }}
            onClick={() => setShowAdvanced(true)}
          >
            Advanced settings
          </button>
        ) : (
          <div style={{ display: "flex", gap: 10 }}>
            <div className="field" style={{ flex: 1 }}><label>Port</label><input className="input" type="number" value={form.port} onChange={update("port")} /></div>
            <div className="field" style={{ flex: 2 }}>
              <label>Custom connection path</label>
              <input className="input" value={form.path} onChange={update("path")} placeholder="/onvif/device_service" />
            </div>
          </div>
        )}

        {error && (
          <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: 0 }}>
            Couldn't connect — double-check the username and password, or that the camera is turned on and connected
            to the same network. ({error})
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Connecting…" : "Connect & add"}</button>
        </div>
      </form>
    </div>
  );
}

export default function CamerasPage({ onOpenCamera, onCameraCountChange, active }) {
  const [configured, setConfigured] = useState([]);
  const [discovered, setDiscovered] = useState([]);
  const [sweepHits, setSweepHits] = useState([]);
  const [statusById, setStatusById] = useState({});
  const [scanning, setScanning] = useState(false);
  const [scanPct, setScanPct] = useState(0);
  const [hasScanned, setHasScanned] = useState(false);
  const [scanError, setScanError] = useState(null);
  const [sweepError, setSweepError] = useState(null);
  const [selectMode, setSelectMode] = useState(false);
  const [picked, setPicked] = useState(new Set());
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPrefill, setManualPrefill] = useState({ hostname: "", vendor: null, port: 80 });
  const [bulkOpen, setBulkOpen] = useState(false);
  const scanTimer = useRef(null);

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
      window.cameraAPI
        .testConnection(camera)
        .then(() => setStatusById((s) => ({ ...s, [camera.id]: "ok" })))
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

  const startScan = async () => {
    setScanning(true);
    setScanError(null);
    setSweepError(null);
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

    if (discoverResult.status === "fulfilled") setDiscovered(discoverResult.value);
    else setScanError(discoverResult.reason?.message ?? String(discoverResult.reason));

    if (sweepResult.status === "fulfilled") setSweepHits(sweepResult.value);
    else setSweepError(sweepResult.reason?.message ?? String(sweepResult.reason));

    clearInterval(scanTimer.current);
    setScanPct(100);
    setHasScanned(true);
    setTimeout(() => setScanning(false), 200);
  };

  useEffect(() => () => clearInterval(scanTimer.current), []);

  const cards = buildCards({ configured, discovered, sweepHits, statusById });
  const isEmpty = !scanning && hasScanned === false && cards.length === 0;
  const needsAttentionCount = cards.filter((c) => c.kind !== "configured").length;

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
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2 }}>
            {scanning ? "Looking for cameras" : cards.length === 0 ? "Cameras" : `${cards.length} camera${cards.length === 1 ? "" : "s"}`}
          </div>
          <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            {scanning ? "This takes a few seconds…" : cards.length === 0 ? "Nothing found yet" : "Found automatically, or added by hand"}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          {selectFeatureEnabled && (
            <button className="btn btn-secondary" onClick={() => setSelectMode((v) => !v)}>
              <i className="ph ph-check-square-offset" style={{ fontSize: 15 }} />Select
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => openManual()}>
            <i className="ph ph-plus" style={{ fontSize: 15 }} />Add manually
          </button>
          <button className="btn btn-primary" onClick={startScan} disabled={scanning}>
            <i className="ph ph-radar" style={{ fontSize: 16 }} />{scanning ? "Scanning…" : "Scan"}
          </button>
        </div>
      </div>

      {scanning && (
        <div style={{ flex: "none", margin: "0 22px 14px", padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>Checking every device on your network…</span>
            <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: 12.5 }} onClick={() => { clearInterval(scanTimer.current); setScanning(false); }}>Stop</button>
          </div>
          <div style={{ height: 3, borderRadius: 2, background: "color-mix(in srgb, var(--color-text) 10%, transparent)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${scanPct}%`, background: "var(--color-accent)", transition: "width .12s linear" }} />
          </div>
        </div>
      )}

      {(scanError || sweepError) && (
        <p style={{ margin: "0 22px 12px", fontSize: 13, color: "var(--color-accent-2-400)" }}>
          The scan ran into a problem, but you can still add a camera by hand below.
        </p>
      )}

      {!scanning && needsAttentionCount > 0 && (
        <p style={{ margin: "0 22px 12px", fontSize: 13, color: "color-mix(in srgb, var(--color-text) 65%, transparent)" }}>
          {needsAttentionCount === 1
            ? "We found something that might be your camera below — tap it to finish setting it up."
            : `We found ${needsAttentionCount} things below that might be your cameras — tap one to finish setting it up.`}
        </p>
      )}

      {selectMode && (
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 10, margin: "0 22px 12px", padding: "8px 14px", borderRadius: "var(--radius-md)", background: "var(--color-accent-900)" }}>
          <span style={{ fontSize: 12.5, fontWeight: 500, color: "var(--color-accent-200)" }}>{picked.size} of {cards.length} selected</span>
          <div style={{ width: 1, height: 14, background: "var(--color-accent-700)" }} />
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-key" style={{ fontSize: 14 }} />Sign in</button>
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-clock-clockwise" style={{ fontSize: 14 }} />Sync time</button>
          <button className="btn btn-ghost" style={{ fontSize: 12.5 }} onClick={() => setBulkOpen(true)}><i className="ph ph-arrow-circle-up" style={{ fontSize: 14 }} />Update firmware</button>
          <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }} onClick={() => { setSelectMode(false); setPicked(new Set()); }}>Done</button>
        </div>
      )}

      {isEmpty ? (
        <div style={{ flex: 1, display: "grid", placeItems: "center", padding: "0 22px 40px" }}>
          <div style={{ maxWidth: 420, textAlign: "center" }}>
            <div style={{ width: 104, height: 104, margin: "0 auto 18px", borderRadius: "50%", display: "grid", placeItems: "center", background: "radial-gradient(circle, var(--color-accent-900), transparent 70%)" }}>
              <i className="ph ph-radar" style={{ fontSize: 44, color: "var(--color-accent)" }} />
            </div>
            <div style={{ fontFamily: "var(--font-heading)", fontSize: 22, marginBottom: 6 }}>No cameras added yet</div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "color-mix(in srgb, var(--color-text) 60%, transparent)" }}>
              picvision can look for cameras on your Wi-Fi network for you — usually takes just a few seconds. If it
              doesn't find yours, you can add it yourself using its IP address instead.
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
              <button className="btn btn-primary" onClick={startScan}><i className="ph ph-radar" style={{ fontSize: 16 }} />Scan this network</button>
              <button className="btn btn-secondary" onClick={() => openManual()}>Add manually</button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 22px 22px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {cards.map((card) => (
              <CameraCard key={card.key} card={card} selectMode={selectMode} picked={picked.has(card.key)} onOpen={() => handleCardOpen(card)} onDismiss={() => dismissDevice(card.key)} />
            ))}
          </div>
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
            <div className="dialog-title">Apply to {picked.size} camera{picked.size === 1 ? "" : "s"}</div>
            <div className="dialog-body">
              Bulk sign-in / sync-time / firmware-update aren't wired up yet — this needs stored credential sets
              to actually run against real cameras, which doesn't exist here.
            </div>
            <div className="dialog-actions">
              <button className="btn btn-secondary" onClick={() => setBulkOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
