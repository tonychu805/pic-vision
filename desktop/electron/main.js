import { app, BrowserWindow, ipcMain } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { discoverCameras } from "./cameras/discovery.js";
import { sweepNetwork } from "./cameras/networkSweep.js";
import { listCameras, addCamera, removeCamera, testConnection } from "./cameras/store.js";
import { getNetworkInfo } from "./system.js";

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
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  registerCameraHandlers();
  registerWindowControlHandlers();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
