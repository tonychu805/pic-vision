import { app, BrowserWindow, ipcMain } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { discoverCameras } from "./cameras/discovery.js";
import { sweepNetwork } from "./cameras/networkSweep.js";
import {
  listCameras,
  addCamera,
  removeCamera,
  renameCamera,
  testConnection,
  probeRtspFallback,
  addCameraViaRtsp,
  parseRtspUrl,
  setCalibPath,
  addCameraFromSampleClip,
} from "./cameras/store.js";
import { getNetworkInfo, pickCalibFile, pickVideoFile } from "./system.js";
import { stopAllRecordings, recordingStatus, listRecordings, discardAllSnapshots } from "./capture.js";
import { runCloudJob, pipelineStatus, pipelineStatusForRecording, cancelCloudJob } from "./pipeline.js";
import { disconnectCloud, getCloudConnection, startHeartbeatLoop, getAgentName, setAgentName, getOrCreateDeviceId } from "./cloud.js";
import { signIn, signOut, getSession, getBrand, registerDevice } from "./auth.js";
import { capture, shutdownAnalytics, isFeatureEnabled } from "./analytics.js";
import { startLiveView, stopLiveView } from "./liveview.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = !app.isPackaged;

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
  ipcMain.handle("cameras:list", async () => {
    return listCameras();
  });
  ipcMain.handle("cameras:add", async (_event, config) => {
    return addCamera(config);
  });
  ipcMain.handle("cameras:remove", async (_event, id) => {
    return removeCamera(id);
  });
  ipcMain.handle("cameras:rename", async (_event, id, label) => {
    return renameCamera(id, label);
  });
  ipcMain.handle("cameras:testConnection", async (_event, config) => {
    return testConnection(config);
  });
  ipcMain.handle("system:networkInfo", async () => {
    return getNetworkInfo();
  });
  ipcMain.handle("cameras:sweep", async (_event, options) => {
    const { cidr, address } = getNetworkInfo();
    return sweepNetwork({ ...options, cidr, excludeHost: address });
  });
  // RTSP-direct fallback (2026-09-01) -- for cameras where ONVIF doesn't
  // work at all but a real stream exists anyway. See store.js's own
  // comment on why this isn't a lesser path: the product needs a stream,
  // not ONVIF specifically.
  ipcMain.handle("cameras:probeRtspFallback", async (_event, config) => {
    return probeRtspFallback(config);
  });
  ipcMain.handle("cameras:addRtsp", async (_event, config) => {
    return addCameraViaRtsp(config);
  });
  ipcMain.handle("cameras:parseRtspUrl", async (_event, raw, fallbackUsername, fallbackPassword) => {
    return parseRtspUrl(raw, fallbackUsername, fallbackPassword);
  });
  ipcMain.handle("cameras:setCalibPath", async (_event, id, calibPath) => {
    return setCalibPath(id, calibPath);
  });
  ipcMain.handle("system:pickCalibFile", async () => {
    return pickCalibFile();
  });
  // "Sample clip" source (2026-09-03) -- ManualAddDialog's dropdown
  // alternative to a live camera, for exercising calibration/the cloud
  // pipeline without one. See store.js's addCameraFromSampleClip.
  ipcMain.handle("cameras:addSampleClip", async (_event, config) => {
    return addCameraFromSampleClip(config);
  });
  ipcMain.handle("system:pickVideoFile", async () => {
    return pickVideoFile();
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

// Hands a finished recording to cloud_pipeline/run_desktop_job.py
// (pipeline.js) -- PIC-68. Looks the camera's calibPath up server-side
// (setCalibPath's IPC handler above is the only way it gets set) rather
// than trusting one the renderer might pass in, same trust-boundary
// convention as registerCaptureHandlers looking up the full camera object
// instead of accepting credentials from the renderer.
function registerPipelineHandlers() {
  ipcMain.handle("pipeline:run", async (_event, { cameraId, recordingDir, targetSec }) => {
    const camera = listCameras().find((c) => c.id === cameraId);
    if (!camera) throw new Error("Camera not found");
    if (!camera.calibPath) throw new Error("No calibration file set for this camera");
    const sessionId = `${camera.label}-${path.basename(recordingDir)}`.replace(/[^a-zA-Z0-9._-]+/g, "_");
    // A sample-clip camera's one "recording" IS the uploaded file already
    // -- no segments to concatenate, so pipeline.js's videoPath override
    // is passed straight through instead of looking for session-*.mkv
    // files that were never written for this camera.
    const videoPath = camera.connectionType === "sampleClip" ? camera.sampleClipPath : undefined;
    return runCloudJob({
      recordingDir, videoPath, calibPath: camera.calibPath, targetSec, sessionId,
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
    return getCloudConnection();
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
  registerCameraHandlers();
  registerCaptureHandlers();
  registerPipelineHandlers();
  registerCloudHandlers();
  registerAuthHandlers();
  registerAnalyticsHandlers();
  registerLiveViewHandlers();
  registerWindowControlHandlers();
  createWindow();
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
