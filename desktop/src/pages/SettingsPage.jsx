import { useEffect, useState } from "react";
import { cleanIpcError } from "../lib/ipcError.js";
import { useI18n } from "../i18n.jsx";
import LanguageSwitch from "../components/LanguageSwitch.jsx";

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

function describeRange(input, t) {
  const trimmed = input.trim();
  if (BARE_IP_RE.test(trimmed)) {
    const base = trimmed.replace(/\.\d{1,3}$/, ".0");
    return { ok: true, text: t("settings.where.willAdd", { base }) };
  }
  const match = trimmed.match(CIDR_RE);
  if (!match) return null;
  const prefix = Number(match[2]);
  if (prefix > 32) return null;
  const count = Math.max(0, 2 ** (32 - prefix) - 2);
  if (count > MAX_HOSTS) return { ok: false, text: t("settings.where.tooMany", { count, cap: MAX_HOSTS }) };
  return { ok: true, text: t("settings.where.count", { count }) };
}

export default function SettingsPage() {
  const { t } = useI18n();
  const [localNetworks, setLocalNetworks] = useState([]);
  const [extraRanges, setExtraRanges] = useState([]);
  const [newRange, setNewRange] = useState("");
  const [rangeError, setRangeError] = useState("");
  const [addingRange, setAddingRange] = useState(false);
  const rangeHint = newRange.trim() ? describeRange(newRange, t) : null;

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
    window.systemAPI?.getNetworkInfo().then((info) => {
      const networks = info?.networks?.length
        ? info.networks
        : info?.cidr ? [{ cidr: info.cidr, interfaceNames: [info.interfaceName], addresses: [info.address] }] : [];
      setLocalNetworks(networks);
    });
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
      setRangeError(cleanIpcError(err, t));
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
      setTimeoutError(cleanIpcError(err, t));
    }
    setSavingTimeout(false);
  };

  return (
    <div className="page">
      {/* In the sidebar again (2026-09-29). It left the sidebar when all it
          held was the Scan button's options; since then it gained "Keep this
          computer ready" and "Send in parts while recording" -- what decides
          whether a booked recording happens at all -- and nobody looks for
          those under "Scan options". The Cameras page's scan icon still
          opens this page. */}
      <div className="page-title" style={{ marginBottom: 16 }}>{t("settings.title")}</div>

      {/* One column, not a 1fr 1fr grid: the right-hand panel holds a
          single number field and ended about a third of the way down the
          left one, leaving a large empty block beside a tall panel. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 560 }}>
        <LanguageCard />
        <PowerCard />
        <AutoSplitCard />

        <div>
          <div className="page-title" style={{ fontSize: "var(--fs-strong)", margin: "10px 0 2px" }}>{t("settings.finding.title")}</div>
          <p className="page-sub" style={{ margin: 0 }}>
            {t("settings.finding.sub")}
          </p>
        </div>

        <div className="card">
          <div className="section-label">{t("settings.where.title")}</div>
          {localNetworks.length === 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
              <i className="ph ph-wifi-high" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)" }}>{t("settings.where.detecting")}</span>
            </div>
          ) : localNetworks.map((network) => (
            <div key={network.cidr} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
              <i className="ph ph-network" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)" }}>{network.cidr}</span>
              <span className="text-4" style={{ fontSize: "var(--fs-fine)" }}>{t("settings.where.alwaysScanned", { interfaces: network.interfaceNames?.join(", ") || t("settings.where.thisMachine") })}</span>
            </div>
          ))}
          {extraRanges.map((cidr) => (
            <div key={cidr} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
              <i className="ph ph-network" style={{ fontSize: 15, color: "var(--color-accent-300)" }} />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)", flex: 1 }}>{cidr}</span>
              <button type="button" className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", padding: 0 }} onClick={() => removeRange(cidr)}>
                {t("settings.where.remove")}
              </button>
            </div>
          ))}
          <form onSubmit={addRange} style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="input"
              placeholder={t("settings.where.placeholder")}
              value={newRange}
              onChange={(e) => { setNewRange(e.target.value); setRangeError(""); }}
              style={{ flex: 1, fontFamily: "var(--font-mono)" }}
            />
            <button className="btn btn-secondary" disabled={addingRange || !newRange.trim() || rangeHint?.ok === false}>
              {addingRange ? t("settings.where.adding") : t("settings.where.add")}
            </button>
          </form>
          {rangeHint && (
            <p style={{ color: rangeHint.ok ? "var(--text-3)" : "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>
              {rangeHint.text}
            </p>
          )}
          {rangeError && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "8px 0 0" }}>{rangeError}</p>}
          <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
            {t("settings.where.note")}
          </p>
          <details className="text-3" style={{ marginTop: 10, fontSize: "var(--fs-fine)" }}>
            <summary style={{ cursor: "pointer" }}>{t("settings.where.vlanQ")}</summary>
            <p style={{ lineHeight: 1.5, margin: "8px 0 0" }}>
              {t("settings.where.vlanA")}
            </p>
          </details>
        </div>

        <div className="card">
          <div className="section-label">{t("settings.wait.title")}</div>
          <div className="field">
            <label>{t("settings.wait.label")}</label>
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
            <span className="text-4" style={{ fontSize: "var(--fs-fine)", marginLeft: 8 }}>{t("settings.wait.unit")}</span>
          </div>
          {savingTimeout && <span className="text-3" style={{ fontSize: "var(--fs-fine)" }}>{t("settings.wait.saving")}</span>}
          {timeoutSaved && !savingTimeout && (
            <span style={{ fontSize: "var(--fs-fine)", color: "var(--color-success)" }}>
              <i className="ph ph-check" style={{ fontSize: 12, marginRight: 4 }} />{t("settings.wait.saved")}
            </span>
          )}
          {timeoutError && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>{timeoutError}</p>}
          <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
            {t("settings.wait.note")}
          </p>
        </div>
      </div>
    </div>
  );
}

// Sending a recording in parts while it records (desktop/electron/autoSplit.js).
// Saves on change, like the Appearance-style switches elsewhere: a setting
// that needs a separate Save press reads as on while it isn't.
function AutoSplitCard() {
  const { t } = useI18n();
  const [minutes, setMinutes] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => { window.autoSplitAPI?.get().then((r) => setMinutes(r.minutes)).catch(() => setMinutes(0)); }, []);

  const change = async (value) => {
    setError("");
    try {
      const saved = await window.autoSplitAPI.set(Number(value));
      setMinutes(saved.minutes);
    } catch (err) {
      setError(err.message || String(err));
    }
  };

  return (
    <div className="card">
      <div className="section-label">{t("settings.parts.title")}</div>
      <div className="field">
        <label>{t("settings.parts.label")}</label>
        <select className="input" style={{ maxWidth: 280 }} value={minutes ?? 0} disabled={minutes === null} onChange={(e) => change(e.target.value)}>
          <option value={0}>{t("settings.parts.off")}</option>
          {[5, 10, 20, 30, 60].map((n) => <option key={n} value={n}>{t("settings.parts.minutes", { n })}</option>)}
        </select>
      </div>
      {error && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>{error}</p>}
      <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
        {t("settings.parts.note")}
      </p>
    </div>
  );
}

// Keeping this computer ready for bookings (electron/power.js): awake while
// the app runs, and the app opening at login. Both on by default.
function PowerCard() {
  const { t } = useI18n();
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { window.powerAPI?.get().then(setSettings).catch(() => setSettings(null)); }, []);

  async function change(setter, on) {
    setError(null);
    try {
      setSettings(await window.powerAPI[setter](on));
    } catch (err) {
      setError(err.message);
    }
  }

  if (!settings) return null;
  return (
    <div className="card">
      <div className="section-label">{t("settings.power.title")}</div>
      <label className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input type="checkbox" checked={settings.keepAwake} onChange={(e) => change("setKeepAwake", e.target.checked)} />
        {t("settings.power.awake")}
      </label>
      <label className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input type="checkbox" checked={settings.openAtLogin} disabled={!settings.loginItemAvailable}
          onChange={(e) => change("setOpenAtLogin", e.target.checked)} />
        {t("settings.power.login")}
      </label>
      {error && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-fine)", margin: "6px 0 0" }}>{error}</p>}
      <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
        {t("settings.power.note")}
      </p>
    </div>
  );
}

// Which language the app shows. The choice is saved by the main process, so it
// survives a restart and also decides what the tray menu says.
function LanguageCard() {
  const { t } = useI18n();
  return (
    <div className="card">
      <div className="section-label">{t("settings.language.title")}</div>
      <div className="field">
        <label>{t("settings.language.label")}</label>
        <LanguageSwitch />
      </div>
      <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0", lineHeight: 1.5 }}>
        {t("settings.language.note")}
      </p>
    </div>
  );
}
