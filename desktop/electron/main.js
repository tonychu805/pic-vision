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
} from "./cameras/store.js";
import { getNetworkInfo } from "./system.js";
import { listSessions, addSession, removeSession, renameSession, listSchedules, removeSchedule } from "./schedule.js";
import { startRecording, stopRecording, stopAllRecordings, recordingStatus } from "./capture.js";

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
    const cameras = removeCamera(id);
    removeSchedule(id); // no orphaned schedule left behind for a deleted camera
    return cameras;
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
}

// Per-camera booked sessions (schedule.js) -- storage + UI only, see that
// file's header for why nothing here actually starts/stops capture yet
// (PIC-66 doesn't exist).
function registerScheduleHandlers() {
  ipcMain.handle("schedule:list", async (_event, cameraId) => {
    return listSessions(cameraId);
  });
  ipcMain.handle("schedule:add", async (_event, cameraId, session) => {
    return addSession(cameraId, session);
  });
  ipcMain.handle("schedule:remove", async (_event, cameraId, sessionId) => {
    return removeSession(cameraId, sessionId);
  });
  ipcMain.handle("schedule:rename", async (_event, cameraId, sessionId, label) => {
    return renameSession(cameraId, sessionId, label);
  });
  ipcMain.handle("schedule:listAll", async () => {
    return listSchedules();
  });
}

// Manual start/stop recording (capture.js) -- PIC-66. Takes just a
// cameraId, not credentials from the renderer -- looks the full camera
// object (including its stored password) up server-side via
// listCameras(), same trust boundary as everything else here.
function registerCaptureHandlers() {
  ipcMain.handle("capture:start", async (_event, cameraId) => {
    const camera = listCameras().find((c) => c.id === cameraId);
    if (!camera) throw new Error("Camera not found");
    return startRecording(camera);
  });
  ipcMain.handle("capture:stop", async (_event, cameraId) => {
    return stopRecording(cameraId);
  });
  ipcMain.handle("capture:status", async (_event, cameraId) => {
    return recordingStatus(cameraId);
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
  registerScheduleHandlers();
  registerCaptureHandlers();
  registerWindowControlHandlers();
  createWindow();

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
  app.exit(0);
});
