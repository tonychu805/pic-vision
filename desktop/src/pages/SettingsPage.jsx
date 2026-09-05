import { useEffect, useState } from "react";

// Real scan configuration (2026-09-05) -- replaces the original mockup's
// 4-panel layout. Only two of those panels mapped onto something real:
// "Ranges" (networkSweep.js's sweepNetwork already took an arbitrary
// cidr, only the auto-detected one was ever passed in) and the
// per-address timeout buried in "Behaviour" (also already a real
// sweepNetwork parameter, just hardcoded to 400ms in CamerasPage.jsx).
// Dropped entirely, not left disabled: "How scanning works" protocol
// checkboxes (4 of 7 don't exist in code at all -- mDNS/Bonjour, SSDP/
// UPnP, vendor probes, RTSP stream probe -- and the 3 that are real
// already run unconditionally, nothing to toggle), and the "Scan when
// picvision opens" cadence radios (auto-scan-on-launch was already
// explicitly removed once, 2026-09-03, "operator's call" -- rebuilding
// it as a setting would quietly re-open that decision). "Previews" stays
// -- it was already accurate static text, not a mock control.
export default function SettingsPage() {
  const [primaryCidr, setPrimaryCidr] = useState(null);
  const [extraRanges, setExtraRanges] = useState([]);
  const [newRange, setNewRange] = useState("");
  const [rangeError, setRangeError] = useState("");
  const [addingRange, setAddingRange] = useState(false);

  const [timeoutMs, setTimeoutMsField] = useState("");
  const [savedTimeoutMs, setSavedTimeoutMs] = useState(null);
  const [timeoutError, setTimeoutError] = useState("");
  const [savingTimeout, setSavingTimeout] = useState(false);

  useEffect(() => {
    window.systemAPI?.getNetworkInfo().then((info) => setPrimaryCidr(info?.cidr ?? null));
    window.scanSettingsAPI?.get().then(({ extraRanges, timeoutMs }) => {
      setExtraRanges(extraRanges);
      setTimeoutMsField(String(timeoutMs));
      setSavedTimeoutMs(timeoutMs);
    });
  }, []);

  const addRange = async (e) => {
    e.preventDefault();
    setAddingRange(true);
    setRangeError("");
    try {
      setExtraRanges(await window.scanSettingsAPI.addRange(newRange));
      setNewRange("");
    } catch (err) {
      setRangeError(err.message);
    }
    setAddingRange(false);
  };

  const removeRange = async (cidr) => {
    setExtraRanges(await window.scanSettingsAPI.removeRange(cidr));
  };

  const saveTimeout = async () => {
    const trimmed = timeoutMs.trim();
    if (!trimmed || Number(trimmed) === savedTimeoutMs) return;
    setSavingTimeout(true);
    setTimeoutError("");
    try {
      const saved = await window.scanSettingsAPI.setTimeout(Number(trimmed));
      setTimeoutMsField(String(saved));
      setSavedTimeoutMs(saved);
    } catch (err) {
      setTimeoutError(err.message);
    }
    setSavingTimeout(false);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "16px 22px 26px" }}>
      <div style={{ fontFamily: "var(--font-heading)", fontSize: 20, lineHeight: 1.2, marginBottom: 4 }}>Scan settings</div>
      <p style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)", margin: "0 0 16px" }}>
        "Scan" on the Cameras page already checks your whole network automatically. These settings extend that when
        the default doesn't cover your setup.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "start" }}>
        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Ranges</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
            <i className="ph ph-wifi-high" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
            <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5 }}>{primaryCidr || "detecting…"}</span>
            <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 45%, transparent)" }}>this machine — always scanned</span>
          </div>
          {extraRanges.map((cidr) => (
            <div key={cidr} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
              <i className="ph ph-network" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5, flex: 1 }}>{cidr}</span>
              <button type="button" className="btn btn-ghost" style={{ fontSize: 11.5, padding: 0 }} onClick={() => removeRange(cidr)}>
                Remove
              </button>
            </div>
          ))}
          <form onSubmit={addRange} style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="input"
              placeholder="192.168.1.0/24"
              value={newRange}
              onChange={(e) => setNewRange(e.target.value)}
              style={{ flex: 1, fontFamily: "ui-monospace, Menlo, monospace" }}
            />
            <button className="btn btn-secondary" disabled={addingRange || !newRange.trim()}>
              {addingRange ? "Adding…" : "Add"}
            </button>
          </form>
          {rangeError && <p style={{ color: "var(--color-accent-2-400)", fontSize: 12, margin: "8px 0 0" }}>{rangeError}</p>}
          <p style={{ fontSize: 11.5, color: "color-mix(in srgb, var(--color-text) 45%, transparent)", margin: "10px 0 0", lineHeight: 1.5 }}>
            Only extends the RTSP port sweep — useful if your cameras sit on a separate VLAN from this machine.
            ONVIF discovery can't reach a different subnet no matter what's added here.
          </p>
        </div>

        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Timeout</div>
          <div className="field">
            <label>Per-address timeout (ms)</label>
            <input
              className="input"
              type="number"
              min="50"
              max="10000"
              value={timeoutMs}
              onChange={(e) => setTimeoutMsField(e.target.value)}
              onBlur={saveTimeout}
              onKeyDown={(e) => e.key === "Enter" && saveTimeout()}
              style={{ maxWidth: 140 }}
            />
          </div>
          {savingTimeout && <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Saving…</span>}
          {timeoutError && <p style={{ color: "var(--color-accent-2-400)", fontSize: 12, margin: "6px 0 0" }}>{timeoutError}</p>}
          <p style={{ fontSize: 11.5, color: "color-mix(in srgb, var(--color-text) 45%, transparent)", margin: "10px 0 0", lineHeight: 1.5 }}>
            How long to wait for a reply from each address during the RTSP port sweep. Lower is faster but can miss
            a slow-to-respond camera; higher is more thorough but takes longer on a large network.
          </p>
        </div>

        <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", gridColumn: "1 / -1" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Previews</div>
          <p style={{ fontSize: 12, lineHeight: 1.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: 0 }}>
            This app doesn't decode live video previews — see the camera detail page's Streams panel for the raw
            RTSP URL instead.
          </p>
        </div>
      </div>
    </div>
  );
}
