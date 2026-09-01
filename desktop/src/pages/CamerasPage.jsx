import { useEffect, useRef, useState } from "react";
import CameraCard from "../components/CameraCard.jsx";
import { buildCards } from "../lib/cameraView.js";

const SCAN_TIMEOUT_MS = 5000;

function ManualAddDialog({ initialHostname = "", onClose, onAdded }) {
  const [form, setForm] = useState({ label: "", hostname: initialHostname, port: 80, path: "", username: "", password: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const camera = await window.cameraAPI.add({ ...form, port: Number(form.port) || 80 });
      onAdded(camera);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div className="dialog-backdrop">
      <form className="dialog" onSubmit={submit}>
        <div className="dialog-title">Add a camera manually</div>
        <div className="dialog-body">
          For cameras discovery misses — a different subnet, ONVIF not enabled on the camera, or a non-default
          ONVIF path.
        </div>
        <div className="field"><label>Label (optional)</label><input className="input" value={form.label} onChange={update("label")} placeholder="Court 1 camera" /></div>
        <div className="field"><label>Camera IP / hostname</label><input className="input" value={form.hostname} onChange={update("hostname")} required autoFocus={!initialHostname} /></div>
        <div style={{ display: "flex", gap: 10 }}>
          <div className="field" style={{ flex: 1 }}><label>Port</label><input className="input" type="number" value={form.port} onChange={update("port")} /></div>
          <div className="field" style={{ flex: 2 }}>
            <label>ONVIF path (optional)</label>
            <input className="input" value={form.path} onChange={update("path")} placeholder="/onvif/device_service" autoFocus={!!initialHostname} />
          </div>
        </div>
        <div className="field"><label>Username</label><input className="input" value={form.username} onChange={update("username")} /></div>
        <div className="field"><label>Password</label><input className="input" type="password" value={form.password} onChange={update("password")} /></div>
        {error && <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: 0 }}>{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Connecting…" : "Connect & add"}</button>
        </div>
      </form>
    </div>
  );
}

export default function CamerasPage({ onOpenCamera, onCameraCountChange }) {
  const [configured, setConfigured] = useState([]);
  const [discovered, setDiscovered] = useState([]);
  const [sweepHits, setSweepHits] = useState([]);
  const [statusByHostname, setStatusByHostname] = useState({});
  const [scanning, setScanning] = useState(false);
  const [scanPct, setScanPct] = useState(0);
  const [hasScanned, setHasScanned] = useState(false);
  const [scanError, setScanError] = useState(null);
  const [sweepError, setSweepError] = useState(null);
  const [selectMode, setSelectMode] = useState(false);
  const [picked, setPicked] = useState(new Set());
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPrefill, setManualPrefill] = useState("");
  const [bulkOpen, setBulkOpen] = useState(false);
  const scanTimer = useRef(null);

  const refreshConfigured = async () => {
    const cameras = await window.cameraAPI.list();
    setConfigured(cameras);
    for (const camera of cameras) {
      setStatusByHostname((s) => ({ ...s, [camera.hostname]: "checking" }));
      window.cameraAPI
        .testConnection(camera)
        .then(() => setStatusByHostname((s) => ({ ...s, [camera.hostname]: "ok" })))
        .catch(() => setStatusByHostname((s) => ({ ...s, [camera.hostname]: "offline" })));
    }
  };

  useEffect(() => {
    refreshConfigured();
  }, []);

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
    const [discoverResult, sweepResult] = await Promise.allSettled([
      window.cameraAPI.discover({ timeout: SCAN_TIMEOUT_MS }),
      window.cameraAPI.sweep({ timeoutMs: 400 }),
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

  const cards = buildCards({ configured, discovered, sweepHits, statusByHostname });
  const isEmpty = !scanning && hasScanned === false && cards.length === 0;

  useEffect(() => {
    onCameraCountChange?.(cards.length);
  }, [cards.length]);

  const togglePick = (key) => setPicked((p) => { const next = new Set(p); next.has(key) ? next.delete(key) : next.add(key); return next; });

  const openManual = (hostname = "") => {
    setManualPrefill(hostname);
    setManualOpen(true);
  };

  const handleCardOpen = (card) => {
    if (selectMode) return togglePick(card.key);
    // Sweep hits don't have a working ONVIF path (or even a confirmed
    // ONVIF service) yet -- there's no detail page to show, so send
    // straight to manual-add, prefilled, rather than a page with nothing
    // real on it.
    if (card.kind === "sweep") return openManual(card.device.hostname);
    onOpenCamera(card);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 12, padding: "16px 22px 12px" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2 }}>
            {scanning ? "Looking for cameras" : cards.length === 0 ? "Cameras" : `${cards.length} camera${cards.length === 1 ? "" : "s"}`}
          </div>
          <div style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>
            {scanning ? `Found ${discovered.length + sweepHits.length} so far` : cards.length === 0 ? "Nothing discovered yet" : "ONVIF discovery + port sweep + manually added"}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          <button className="btn btn-secondary" onClick={() => setSelectMode((v) => !v)}>
            <i className="ph ph-check-square-offset" style={{ fontSize: 15 }} />Select
          </button>
          <button className="btn btn-secondary" onClick={() => openManual()}>
            <i className="ph ph-plus" style={{ fontSize: 15 }} />Add manually
          </button>
          <button className="btn btn-primary" onClick={startScan} disabled={scanning}>
            <i className="ph ph-radar" style={{ fontSize: 16 }} />{scanning ? "Scanning…" : "Scan again"}
          </button>
        </div>
      </div>

      {scanning && (
        <div style={{ flex: "none", margin: "0 22px 14px", padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>ONVIF WS-Discovery + RTSP port sweep</span>
            <button className="btn btn-ghost" style={{ marginLeft: "auto", fontSize: 12.5 }} onClick={() => { clearInterval(scanTimer.current); setScanning(false); }}>Stop</button>
          </div>
          <div style={{ height: 3, borderRadius: 2, background: "color-mix(in srgb, var(--color-text) 10%, transparent)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${scanPct}%`, background: "var(--color-accent)", transition: "width .12s linear" }} />
          </div>
        </div>
      )}

      {(scanError || sweepError) && (
        <p style={{ margin: "0 22px 12px", fontSize: 13, color: "var(--color-accent-2-400)" }}>
          {scanError && <>ONVIF discovery failed: {scanError}. </>}
          {sweepError && <>Port sweep failed: {sweepError}. </>}
          You can still add a camera manually.
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
            <div style={{ fontFamily: "var(--font-heading)", fontSize: 22, marginBottom: 6 }}>No court cameras found yet</div>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "color-mix(in srgb, var(--color-text) 60%, transparent)" }}>
              picvision checks this network two ways: ONVIF WS-Discovery (cameras that answer a broadcast probe) and
              an RTSP port sweep (anything with port 554 open, whether it cooperates with discovery or not). If both
              come up empty, add it manually with its IP.
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
              <button className="btn btn-primary" onClick={startScan}><i className="ph ph-radar" style={{ fontSize: 16 }} />Scan this network</button>
              <button className="btn btn-secondary" onClick={() => openManual()}>Add manually</button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 22px 22px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
            {cards.map((card) => (
              <CameraCard key={card.key} card={card} selectMode={selectMode} picked={picked.has(card.key)} onOpen={() => handleCardOpen(card)} />
            ))}
          </div>
        </div>
      )}

      {manualOpen && (
        <ManualAddDialog
          initialHostname={manualPrefill}
          onClose={() => setManualOpen(false)}
          onAdded={() => { setManualOpen(false); refreshConfigured(); }}
        />
      )}

      {bulkOpen && (
        <div className="dialog-backdrop">
          <div className="dialog" style={{ width: "min(520px, 100%)" }}>
            <div className="dialog-title">Apply to {picked.size} camera{picked.size === 1 ? "" : "s"}</div>
            <div className="dialog-body">
              Bulk sign-in / sync-time / firmware-update aren't wired up yet — this needs the Credentials page's
              stored credential sets to actually run against real cameras.
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
