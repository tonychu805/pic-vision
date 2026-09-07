import { app, BrowserWindow, ipcMain } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { discoverCameras } from "./cameras/discovery.js";
import { sweepNetwork } from "./cameras/networkSweep.js";
import { getExtraRanges, addExtraRange, removeExtraRange, getTimeoutMs, setTimeoutMs } from "./scanSettings.js";
import {
  listCameras,
  listCamerasForRenderer,
  publicCamera,
  withStoredSecrets,
  revealStreamUri,
  addCamera,
  removeCamera,
  renameCamera,
  updateCameraCredentials,
  testConnection,
  probeRtspFallback,
  addCameraViaRtsp,
  parseRtspUrl,
  addCameraFromSampleClip,
} from "./cameras/store.js";
import { getNetworkInfo, pickVideoFile, openExternal } from "./system.js";
import { updateState } from "./version.js";
import { classifyProbeError } from "./cameras/probeResult.js";
import { secureStoreFiles } from "./storeFiles.js";
import { stopAllRecordings, recordingStatus, listRecordings, discardAllSnapshots, isRecording } from "./capture.js";
import { runCloudJob, pipelineStatus, pipelineStatusForRecording, cancelCloudJob } from "./pipeline.js";
import { disconnectCloud, getCloudConnection, startHeartbeatLoop, getAgentName, setAgentName, getOrCreateDeviceId, getCalibrationState } from "./cloud.js";
import { signIn, signOut, getSession, getBrand, registerDevice } from "./auth.js";
import { capture, shutdownAnalytics, isFeatureEnabled } from "./analytics.js";
import { startLiveView, stopLiveView } from "./liveview.js";
import { getEvents, clearEvents } from "./activityLog.js";
import { createTray, destroyTray } from "./tray.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = !app.isPackaged;

// Where the app asks "is there a newer version?". Deliberately a constant:
// this URL is baked into every copy handed to a venue and can never
// change, which is exactly why it points at something we own rather than
// at a release host we might swap. Overridable for local testing only.
const UPDATE_FEED_URL =
  process.env.PIC_VISION_UPDATE_URL || "https://console.picvisionai.com/api/desktop/latest";

// All OS/network-touching work (ONVIF discovery, camera connect, persisted
// storage) is registered here, once, behind named ipcMain handlers -- the
// renderer never gets Node/net access directly (preload.js only forwards
// these five calls via contextBridge). Keeping every camera call funneled
// through this one boundary is deliberate: it's what would let a later
// Tauri port keep this whole file as a Node "sidecar" process instead of
// requiring a Rust rewrite (see the Electron-vs-Tauri discussion this came
// out of).
function registerCameraHandlers() {
  ipcMain.handle("cameras:discover", async (_event, options) => {
    return discoverCameras(options);
  });
  // Calibration state is merged in from the console's last heartbeat
  // response rather than stored locally (ADR-084) -- the fit runs on the
  // operator's job runner and lives on the camera's console row, so this
  // machine has no calib.json to look at.
  // Redacted: no password, credentials starred out of streamUri (PIC-97).
  // listCameras() itself stays for internal callers -- capture.js and the
  // heartbeat genuinely need the real credentials.
  ipcMain.handle("cameras:list", async () => {
    return listCamerasForRenderer().map((c) => ({ ...c, ...getCalibrationState(c.id) }));
  });
  // The one deliberate way credentials reach the renderer: the Streams
  // panel's Copy button, so pasting into VLC still works. An explicit act,
  // not something every render does.
  ipcMain.handle("cameras:revealStreamUri", async (_event, id) => {
    return revealStreamUri(id);
  });
  ipcMain.handle("cameras:add", async (_event, config) => {
    return publicCamera(await addCamera(config));
  });
  ipcMain.handle("cameras:remove", async (_event, id) => {
    return removeCamera(id);
  });
  // Re-enter credentials for a camera that's refusing them. Verified
  // against the real camera before anything is saved, so a typo can't
  // replace working credentials with broken ones.
  ipcMain.handle("cameras:updateCredentials", async (_event, id, username, password) => {
    return updateCameraCredentials(id, username, password);
  });
  ipcMain.handle("cameras:rename", async (_event, id, label) => {
    return publicCamera(await renameCamera(id, label));
  });
  // Returns a classification rather than throwing (PIC-93-adjacent, fixed
  // 2026-09-07). The renderer used to do `.catch(() => "offline")`, which
  // threw the error away and rendered "Not answering" for everything --
  // including a camera that answered "401 Unauthorized", where the fix is
  // a password, not a cable. testConnection itself still throws, because
  // cloud.js's heartbeat and store.js's pre-save check both rely on that.
  ipcMain.handle("cameras:testConnection", async (_event, config) => {
    try {
      // withStoredSecrets: the renderer's copy has no password (ADR-088),
      // and it hands that copy straight back here. Without this every
      // configured camera fails its own check with a 401.
      const result = await testConnection(withStoredSecrets(config));
      return { ok: true, state: "ok", ...result };
    } catch (err) {
      return { ok: false, ...classifyProbeError(err) };
    }
  });
  ipcMain.handle("system:networkInfo", async () => {
    return getNetworkInfo();
  });
  // Sweeps the auto-detected primary subnet (unchanged, real-error-on-
  // failure behavior kept exactly as before) plus any operator-added
  // extra ranges (scanSettings.js) -- those are best-effort: a bad or
  // oversized extra range (sweepNetwork's own MAX_HOSTS guard) is logged
  // and skipped rather than failing the whole scan, since the primary
  // range may have found real cameras already.
  ipcMain.handle("cameras:sweep", async () => {
    const { cidr, address } = getNetworkInfo();
    const timeoutMs = getTimeoutMs();
    const primaryHits = await sweepNetwork({ cidr, timeoutMs, excludeHost: address });

    const extraRanges = getExtraRanges().filter((r) => r !== cidr);
    const extraResults = await Promise.allSettled(
      extraRanges.map((r) => sweepNetwork({ cidr: r, timeoutMs, excludeHost: address })),
    );

    const seen = new Set(primaryHits.map((h) => h.hostname));
    const merged = [...primaryHits];
    extraResults.forEach((result, i) => {
      if (result.status !== "fulfilled") {
        console.error(`[scan] extra range ${extraRanges[i]} failed: ${result.reason?.message}`);
        return;
      }
      for (const hit of result.value) {
        if (seen.has(hit.hostname)) continue;
        seen.add(hit.hostname);
        merged.push(hit);
      }
    });
    return merged;
  });
  // RTSP-direct fallback (2026-09-01) -- for cameras where ONVIF doesn't
  // work at all but a real stream exists anyway. See store.js's own
  // comment on why this isn't a lesser path: the product needs a stream,
  // not ONVIF specifically.
  ipcMain.handle("cameras:probeRtspFallback", async (_event, config) => {
    return probeRtspFallback(config);
  });
  ipcMain.handle("cameras:addRtsp", async (_event, config) => {
    return publicCamera(await addCameraViaRtsp(config));
  });
  ipcMain.handle("cameras:parseRtspUrl", async (_event, raw, fallbackUsername, fallbackPassword) => {
    return parseRtspUrl(raw, fallbackUsername, fallbackPassword);
  });
  // "Sample clip" source (2026-09-03) -- ManualAddDialog's dropdown
  // alternative to a live camera, for exercising calibration/the cloud
  // pipeline without one. See store.js's addCameraFromSampleClip.
  ipcMain.handle("cameras:addSampleClip", async (_event, config) => {
    return publicCamera(await addCameraFromSampleClip(config));
  });
  ipcMain.handle("system:pickVideoFile", async () => {
    return pickVideoFile();
  });
  ipcMain.handle("system:openExternal", async (_event, url) => {
    return openExternal(url);
  });

  // Manual update check. Auto-update needs a Developer ID signature that
  // the unsigned venue builds don't have, so the app tells the operator
  // and they install it themselves.
  //
  // The address is fixed rather than read from the paired connection: an
  // agent that was never paired, or whose token was revoked, still needs
  // to be able to find out it's out of date. It points at our own console
  // rather than at GitHub directly so the download location can move later
  // without stranding copies already installed -- see that route's own
  // comment.
  ipcMain.handle("updates:check", async () => {
    const current = app.getVersion();
    try {
      const res = await fetch(UPDATE_FEED_URL, {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return updateState(current, await res.json());
    } catch (err) {
      // Offline venue, DNS, console down. Reported as "couldn't check",
      // never as "up to date".
      console.error(`[updates] check failed: ${err.message}`);
      return { ...updateState(current, null), error: err.message };
    }
  });
}

// Real scan configuration (scanSettings.js) -- 2026-09-05, replacing
// SettingsPage.jsx's mock "Ranges"/"Behaviour" panels.
function registerScanSettingsHandlers() {
  ipcMain.handle("scanSettings:get", async () => {
    return { extraRanges: getExtraRanges(), timeoutMs: getTimeoutMs() };
  });
  ipcMain.handle("scanSettings:addRange", async (_event, cidr) => {
    return addExtraRange(cidr);
  });
  ipcMain.handle("scanSettings:removeRange", async (_event, cidr) => {
    return removeExtraRange(cidr);
  });
  ipcMain.handle("scanSettings:setTimeout", async (_event, ms) => {
    return setTimeoutMs(ms);
  });
}

// Recording status/history (capture.js) -- PIC-66, start/stop removed
// 2026-09-05 (ADR-080): the renderer no longer starts or stops a
// recording directly, only the cloud->agent command channel does
// (cloud.js's runCommand, triggered from the console). startRecording/
// stopRecording themselves are unchanged and still called from there.
function registerCaptureHandlers() {
  ipcMain.handle("capture:status", async (_event, cameraId) => {
    return recordingStatus(cameraId);
  });
  ipcMain.handle("capture:listRecordings", async (_event, cameraId) => {
    const camera = listCameras().find((c) => c.id === cameraId);
    if (!camera) throw new Error("Camera not found");
    return listRecordings(camera);
  });
}

// Hands a finished recording to the cloud for processing (pipeline.js) --
// PIC-68, rewired by ADR-084 to upload to the console rather than run the
// pipeline locally. The camera is looked up here, from its id, rather than
// trusting an object the renderer passes in -- same trust-boundary
// convention as registerCaptureHandlers. The calibration check now lives
// on the console (it holds the calibration), which answers with a real
// message if the camera has never been calibrated.
function registerPipelineHandlers() {
  ipcMain.handle("pipeline:run", async (_event, { cameraId, recordingDir, targetSec }) => {
    const camera = listCameras().find((c) => c.id === cameraId);
    if (!camera) throw new Error("Camera not found");
    const sessionId = `${camera.label}-${path.basename(recordingDir)}`.replace(/[^a-zA-Z0-9._-]+/g, "_");
    // A sample-clip camera's one "recording" IS the uploaded file already
    // -- no segments to concatenate, so pipeline.js's videoPath override
    // is passed straight through instead of looking for session-*.mkv
    // files that were never written for this camera.
    const videoPath = camera.connectionType === "sampleClip" ? camera.sampleClipPath : undefined;
    return runCloudJob({
      recordingDir, videoPath, targetSec, sessionId,
      cameraId: camera.id, cameraLabel: camera.label,
    });
  });
  ipcMain.handle("pipeline:status", async (_event, jobDir) => {
    return pipelineStatus(jobDir);
  });
  ipcMain.handle("pipeline:statusForRecording", async (_event, recordingDir) => {
    return pipelineStatusForRecording(recordingDir);
  });
  ipcMain.handle("pipeline:cancel", async (_event, recordingDir) => {
    return cancelCloudJob(recordingDir);
  });
}

// Device registration + heartbeat (cloud.js) -- the desktop agent's first
// outbound connection to pic-vision-cloud-console, ADR-071's "polls or a
// lightweight persistent connection for commands/status, never an inbound
// port" directive. Registration itself now happens automatically right
// after sign-in (auth.js's `registerDevice`, called from `auth:signIn`
// and at startup below) -- `cloud:register` here is just the manual retry
// CloudPage.jsx offers if that didn't succeed the first time.
function registerCloudHandlers() {
  ipcMain.handle("cloud:register", async () => {
    return registerDevice();
  });
  ipcMain.handle("cloud:status", async () => {
    // apiToken stripped (PIC-97): it's the long-lived credential a revoked
    // device can never recover, and nothing in the UI reads it -- CloudPage
    // uses brandName/connectedAt/consoleUrl only. It was being handed over
    // on every poll for no reason at all.
    const connection = getCloudConnection();
    if (!connection) return connection;
    const { apiToken: _apiToken, ...rest } = connection;
    return rest;
  });
  ipcMain.handle("cloud:disconnect", async () => {
    disconnectCloud();
    return null;
  });
  ipcMain.handle("cloud:getAgentName", async () => {
    return getAgentName();
  });
  ipcMain.handle("cloud:setAgentName", async (_event, name) => {
    return setAgentName(name);
  });
  ipcMain.handle("cloud:getDeviceId", async () => {
    return getOrCreateDeviceId();
  });
}

// Account sign-in (auth.js) -- gates App.jsx's own render. `auth:signIn`
// also triggers registerCloudHandlers()'s device registration internally
// (auth.js's `registerDevice`), so a successful sign-in is what actually
// connects this device to the console.
function registerAuthHandlers() {
  ipcMain.handle("auth:signIn", async (_event, email, password) => {
    return signIn(email, password);
  });
  ipcMain.handle("auth:signOut", async () => {
    return signOut();
  });
  ipcMain.handle("auth:getSession", async () => {
    return getSession();
  });
  ipcMain.handle("auth:getBrand", async () => {
    return getBrand();
  });
}

// One handler, not one per event type -- renderer calls
// window.analyticsAPI.capture(event, properties) for anything it wants
// to log (currently just $pageview on nav change), same shape
// posthog-js's own .capture() takes so call sites read the same either
// way.
function registerAnalyticsHandlers() {
  ipcMain.handle("analytics:capture", (_event, event, properties) => {
    capture(event, properties);
  });
  ipcMain.handle("analytics:isFeatureEnabled", async (_event, key) => {
    return isFeatureEnabled(key);
  });
}

// Real activity history for the Log tab (2026-09-05, replacing the mock
// "Alerts" page) -- activityLog.js is the only source of truth, this is
// just the IPC bridge to it.
function registerActivityLogHandlers() {
  ipcMain.handle("log:list", async () => {
    return getEvents();
  });
  ipcMain.handle("log:clear", async () => {
    clearEvents();
    return null;
  });
}

function registerLiveViewHandlers() {
  ipcMain.handle("liveview:start", async (_event, cameraId) => {
    const camera = listCameras().find((c) => c.id === cameraId);
    if (!camera) throw new Error("camera not found");
    return startLiveView(camera);
  });
  ipcMain.handle("liveview:stop", async () => {
    await stopLiveView();
  });
}

// Registered once against whichever window is currently focused -- a single
// -window POC, but avoids the "second handler for window:minimize" crash
// that registering inside createWindow() would hit on a second
// createWindow() call (e.g. macOS dock re-activate).
function registerWindowControlHandlers() {
  const focused = () => BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  ipcMain.handle("window:minimize", () => focused()?.minimize());
  ipcMain.handle("window:maximize", () => {
    const win = focused();
    if (!win) return;
    win.isMaximized() ? win.unmaximize() : win.maximize();
  });
  ipcMain.handle("window:close", () => focused()?.close());
}

// Frameless -- the mockup (desktop-utility-by-claude-design.zip) draws its
// own title bar (mac traffic-light dots / Windows min-max-close) in HTML
// rather than using the OS chrome, so the real window has to actually be
// frameless for that to be true rather than a decoration drawn under a
// second, real title bar.
function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    frame: false,
    // Taskbar/dock icon while running from source (npm run dev) -- a
    // packaged build gets its icon from package.json's build.icon instead,
    // but that config is only ever read by electron-builder, never by a
    // plain `electron .` launch, so without this the dev window shows
    // Electron's own default icon regardless of what's set there.
    // Dev only, for the same reason as the Dock icon below: build/ isn't
    // packaged, so this path doesn't exist in a built app. A bad `icon`
    // is ignored rather than fatal, unlike app.dock.setIcon -- but a
    // reference to a file that can't be there is a lie either way.
    ...(isDev ? { icon: path.join(__dirname, "..", "build", "icon.png") } : {}),
    // App.jsx's root div already draws borderRadius:12 + overflow:hidden
    // (the mockup's own rounded window) -- but that only clips this
    // window's OWN content. Without the window itself being transparent,
    // the OS still paints a plain opaque rectangle behind it, so the 4
    // corner triangles outside the CSS radius showed as solid squared-off
    // fill instead of true rounded corners. transparent:true lets the
    // desktop show through those corners instead.
    transparent: true,
    backgroundColor: "#00000000",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
    // Used to open unconditionally on every dev launch -- a whole extra
    // Chromium UI surface (detached DevTools window) the compositor has
    // to service on top of the app's own GPU process + 2 renderers,
    // whether or not anyone's actually looking at it. Reported
    // 2026-09-01 as system-wide mouse lag whenever the dev server
    // starts; --remote-debugging-port=9223 (already set in package.json)
    // gives full CDP access without this window at all, which is how
    // this session verifies changes anyway -- opt in with
    // OPEN_DEVTOOLS=1 when actually wanted.
    if (process.env.OPEN_DEVTOOLS) win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  // Before anything reads a credential: tightens the store files to 0600
  // and re-encrypts anything a pre-ADR-082 version left in plaintext.
  // Both were real on 2026-09-07 -- see storeFiles.js.
  secureStoreFiles();
  registerCameraHandlers();
  registerScanSettingsHandlers();
  registerCaptureHandlers();
  registerPipelineHandlers();
  registerCloudHandlers();
  registerAuthHandlers();
  registerAnalyticsHandlers();
  registerActivityLogHandlers();
  registerLiveViewHandlers();
  registerWindowControlHandlers();
  // BrowserWindow's icon option (createWindow) only ever reaches the
  // taskbar on Windows/Linux -- macOS's Dock icon for an unpackaged
  // `electron .` run needs setting separately, or it shows Electron's own
  // default regardless. A packaged build doesn't need this: its Dock icon
  // comes from the .app bundle's Info.plist, built from build.icon.
  //
  // `isDev &&`, not just the platform check, and this cost a release
  // candidate to find (2026-09-07). `build/` isn't in build.files, so
  // build/icon.png does not exist inside a packaged app -- this line threw
  // BEFORE createWindow() and the app started with no window at all. The
  // process stayed alive with a Dock icon, so it looked like it had opened
  // and simply drawn nothing, which a frameless transparent window is
  // indistinguishable from.
  //
  // try/catch as well as the guard: a Dock icon is decoration, and nothing
  // about it is worth taking the whole app down for.
  if (isDev && process.platform === "darwin") {
    try {
      app.dock.setIcon(path.join(__dirname, "..", "build", "icon.png"));
    } catch (err) {
      console.error(`[app] could not set the dev Dock icon: ${err.message}`);
    }
  }
  createWindow();
  // Closing the last macOS window keeps the agent running so recordings and
  // cloud heartbeats continue. The menu-bar item is the visible proof of
  // that state, plus the deliberate place to reopen or quit the app.
  createTray(() => {
    const cameras = listCameras();
    return {
      recordingLabels: cameras.filter((camera) => isRecording(camera.id)).map((camera) => camera.label),
      connection: getCloudConnection(),
    };
  });
  startHeartbeatLoop(); // no-op if never registered; resumes automatically if it was
  // Catches the case where a device is signed in but registration never
  // succeeded (console unreachable the first time, or this is a relaunch
  // right after that failure) -- signIn() only tries once, at sign-in
  // time, so a launch that skips signIn() entirely (an existing session)
  // needs its own chance to retry.
  if (getSession() && !getCloudConnection()) {
    registerDevice().catch((err) => console.error(`[auth] device registration retry failed: ${err.message}`));
  }
  capture("app_launched");

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// A recording is a background ffmpeg process, not tied to any window --
// quitting the app without this would either orphan it (still running,
// invisible) or leave it to the OS to kill outright (SIGKILL-equivalent,
// which ADR-031 found corrupts the output container). before-quit runs
// before Electron actually tears anything down, so this can await a real
// clean SIGINT stop first.
app.on("before-quit", async (e) => {
  e.preventDefault();
  destroyTray();
  await stopAllRecordings();
  await stopLiveView(); // no-op if no live-view popup was open
  // A calibration snapshot left over from a modal closed mid-flow
  // (window closed without Save or Cancel) shouldn't linger in /tmp
  // indefinitely -- real gap found 2026-09-03, where one such leftover
  // was a live, private frame from a real camera.
  discardAllSnapshots();
  await shutdownAnalytics(); // flushes posthog-node's batched queue before the process actually exits
  app.exit(0);
});
