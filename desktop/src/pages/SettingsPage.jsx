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
// it as a setting would quietly re-open that decision). "Previews" was
// kept at first (it was already accurate static text, not a mock
// control) but removed 2026-09-06, operator's call -- it didn't do
// anything a setting page needs to do, just pointed elsewhere.
// Mirrors scanSettings.js's own validation (bare IP -> /24, MAX_HOSTS cap)
// just enough to give live feedback as someone types, before they ever hit
// Add -- the real, authoritative check still happens in the main process;
// this only avoids a submit-fail-retry loop for the common cases.
const BARE_IP_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const CIDR_RE = /^(\d{1,3}\.){3}\d{1,3}\/(\d{1,2})$/;
const MAX_HOSTS = 512; // must match networkSweep.js's MAX_HOSTS

function describeRange(input) {
  const trimmed = input.trim();
  if (BARE_IP_RE.test(trimmed)) {
    const base = trimmed.replace(/\.\d{1,3}$/, ".0");
    return { ok: true, text: `Will add ${base}/24 — 254 addresses` };
  }
  const match = trimmed.match(CIDR_RE);
  if (!match) return null;
  const prefix = Number(match[2]);
  if (prefix > 32) return null;
  const count = Math.max(0, 2 ** (32 - prefix) - 2);
  if (count > MAX_HOSTS) return { ok: false, text: `= ${count} addresses — too many (cap is ${MAX_HOSTS}), narrow this` };
  return { ok: true, text: `= ${count} addresses` };
}

export default function SettingsPage({ onBack }) {
  const [primaryCidr, setPrimaryCidr] = useState(null);
  const [extraRanges, setExtraRanges] = useState([]);
  const [newRange, setNewRange] = useState("");
  const [rangeError, setRangeError] = useState("");
  const [addingRange, setAddingRange] = useState(false);
  const rangeHint = newRange.trim() ? describeRange(newRange) : null;

  const [timeoutMs, setTimeoutMsField] = useState("");
  const [savedTimeoutMs, setSavedTimeoutMs] = useState(null);
  const [timeoutError, setTimeoutError] = useState("");
  const [savingTimeout, setSavingTimeout] = useState(false);
  // Adding a range confirms itself -- the row appears. Blurring the
  // timeout field showed a flash of "Saving…" and then nothing, so there
  // was no way to know it had stuck. Held for a couple of seconds, then
  // cleared.
  const [timeoutSaved, setTimeoutSaved] = useState(false);

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
      setTimeoutSaved(true);
      setTimeout(() => setTimeoutSaved(false), 2200);
    } catch (err) {
      setTimeoutError(err.message);
    }
    setSavingTimeout(false);
  };

  return (
    <div className="page">
      {/* Reached from the Cameras page's "Scan options" now rather than
          from the sidebar, so it needs its own way back -- same pattern
          as the camera detail page. */}
      <button className="btn btn-ghost" style={{ fontSize: "var(--fs-body)", marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />All cameras
      </button>
      <div className="page-title" style={{ marginBottom: 4 }}>Scan options</div>
      <p className="page-sub" style={{ marginBottom: 16 }}>
        "Scan" on the Cameras page already checks your whole network automatically. These settings extend that when
        the default doesn't cover your setup.
      </p>

      {/* One column, not a 1fr 1fr grid: the right-hand panel holds a
          single number field and ended about a third of the way down the
          left one, leaving a large empty block beside a tall panel. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 560 }}>
        <div className="card">
          <div className="section-label">Where to look</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
            <i className="ph ph-wifi-high" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)" }}>{primaryCidr || "detecting…"}</span>
            <span className="text-4" style={{ fontSize: "var(--fs-fine)" }}>this machine — always scanned</span>
          </div>
          {extraRanges.map((cidr) => (
            <div key={cidr} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
              <i className="ph ph-network" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)", flex: 1 }}>{cidr}</span>
              <button type="button" className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", padding: 0 }} onClick={() => removeRange(cidr)}>
                Remove
              </button>
            </div>
          ))}
          <form onSubmit={addRange} style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="input"
              placeholder="192.168.1.50 or 192.168.1.0/24"
              value={newRange}
              onChange={(e) => setNewRange(e.target.value)}
              style={{ flex: 1, fontFamily: "var(--font-mono)" }}
            />
            <button className="btn btn-secondary" disabled={addingRange || !newRange.trim() || rangeHint?.ok === false}>
              {addingRange ? "Adding…" : "Add"}
            </button>
          </form>
          {rangeHint && (
            <p style={{ color: rangeHint.ok ? "var(--text-3)" : "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>
              {rangeHint.text}
            </p>
          )}
          {rangeError && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "8px 0 0" }}>{rangeError}</p>}
          <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
            Only extends the RTSP port sweep — useful if your cameras sit on a separate VLAN from this machine.
            ONVIF discovery can't reach a different subnet no matter what's added here.
          </p>
          <details className="text-3" style={{ marginTop: 10, fontSize: "var(--fs-fine)" }}>
            <summary style={{ cursor: "pointer" }}>Want automatic discovery to reach that VLAN too?</summary>
            <p style={{ lineHeight: 1.5, margin: "8px 0 0" }}>
              That's a network setting, not something this app can turn on. Ask whoever manages the network to enable
              "IGMP Proxy," "Multicast Routing," or "PIM" between the two VLANs on the router/switch that separates
              them — usually under a Routing/Advanced/Multicast section. Most basic consumer routers don't offer
              this; it's typically a prosumer/enterprise feature (Ubiquiti, pfSense, small-business Cisco/Netgear).
              If it's not available, a small relay device on both networks (e.g. a Raspberry Pi running an
              open-source multicast-relay tool) can do the same job. See the desktop README's "Cameras on a
              different network" section for the full writeup.
            </p>
          </details>
        </div>

        <div className="card">
          <div className="section-label">How long to wait</div>
          <div className="field">
            <label>Wait for each device before moving on</label>
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
            <span className="text-4" style={{ fontSize: "var(--fs-fine)", marginLeft: 8 }}>milliseconds</span>
          </div>
          {savingTimeout && <span className="text-3" style={{ fontSize: "var(--fs-fine)" }}>Saving…</span>}
          {timeoutSaved && !savingTimeout && (
            <span style={{ fontSize: "var(--fs-fine)", color: "var(--color-success)" }}>
              <i className="ph ph-check" style={{ fontSize: 12, marginRight: 4 }} />Saved
            </span>
          )}
          {timeoutError && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>{timeoutError}</p>}
          <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
            How long to wait for a reply from each address while checking the network. Lower is faster but can miss
            a slow-to-respond camera; higher is more thorough but takes longer on a large network.
          </p>
        </div>
      </div>
    </div>
  );
}
