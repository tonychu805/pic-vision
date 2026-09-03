// The only bridge between the renderer (untrusted web content) and Node/OS
// access. Exposes a fixed, named set of async calls (cameraAPI/windowAPI/
// systemAPI) plus one static value (platformAPI) -- nothing else from
// Node's API surface reaches the renderer. Renderer components must go
// through these, never reach into Electron/Node directly; that discipline
// is what keeps a later port (Tauri, or a real web app) to a backend-only
// change instead of a full rewrite.
//
// .cjs (not .js) is deliberate: Electron's preload loader resolves module
// type by extension, not by the nearest package.json's "type" field the
// way normal Node/Vite resolution does -- with "type": "module" set for
// the rest of this project, a plain preload.js using `import` here loaded
// silently with no contextBridge calls ever running (no thrown error, no
// console warning -- window.cameraAPI just stayed undefined). Confirmed
// via CDP (Runtime.evaluate against the real renderer, not a guess) before
// landing this fix.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cameraAPI", {
  discover: (options) => ipcRenderer.invoke("cameras:discover", options),
  list: () => ipcRenderer.invoke("cameras:list"),
  add: (config) => ipcRenderer.invoke("cameras:add", config),
  remove: (id) => ipcRenderer.invoke("cameras:remove", id),
  rename: (id, label) => ipcRenderer.invoke("cameras:rename", id, label),
  testConnection: (config) => ipcRenderer.invoke("cameras:testConnection", config),
  sweep: (options) => ipcRenderer.invoke("cameras:sweep", options),
  probeRtspFallback: (config) => ipcRenderer.invoke("cameras:probeRtspFallback", config),
  addRtsp: (config) => ipcRenderer.invoke("cameras:addRtsp", config),
  parseRtspUrl: (raw, fallbackUsername, fallbackPassword) =>
    ipcRenderer.invoke("cameras:parseRtspUrl", raw, fallbackUsername, fallbackPassword),
  setCalibPath: (id, calibPath) => ipcRenderer.invoke("cameras:setCalibPath", id, calibPath),
  addSampleClip: (config) => ipcRenderer.invoke("cameras:addSampleClip", config),
});

// process.platform is a value, not a function -- safe to expose directly
// (contextBridge only refuses functions/objects it can't structured-clone,
// and a string is fine). Drives the mockup's mac-dots-vs-Windows-buttons
// title bar branch.
contextBridge.exposeInMainWorld("platformAPI", {
  platform: process.platform, // 'darwin' | 'win32' | 'linux'
});

contextBridge.exposeInMainWorld("windowAPI", {
  minimize: () => ipcRenderer.invoke("window:minimize"),
  maximize: () => ipcRenderer.invoke("window:maximize"),
  close: () => ipcRenderer.invoke("window:close"),
});

contextBridge.exposeInMainWorld("systemAPI", {
  getNetworkInfo: () => ipcRenderer.invoke("system:networkInfo"),
  pickCalibFile: () => ipcRenderer.invoke("system:pickCalibFile"),
  pickVideoFile: () => ipcRenderer.invoke("system:pickVideoFile"),
});

contextBridge.exposeInMainWorld("captureAPI", {
  start: (cameraId) => ipcRenderer.invoke("capture:start", cameraId),
  stop: (cameraId) => ipcRenderer.invoke("capture:stop", cameraId),
  status: (cameraId) => ipcRenderer.invoke("capture:status", cameraId),
  listRecordings: (cameraId) => ipcRenderer.invoke("capture:listRecordings", cameraId),
});

contextBridge.exposeInMainWorld("calibrationAPI", {
  snapshot: (cameraId, atSec) => ipcRenderer.invoke("calibration:snapshot", cameraId, atSec),
  discardSnapshot: (snapshotPath) => ipcRenderer.invoke("calibration:discardSnapshot", snapshotPath),
  save: (cameraId, snapshotPath, points) => ipcRenderer.invoke("calibration:save", cameraId, snapshotPath, points),
});

contextBridge.exposeInMainWorld("pipelineAPI", {
  run: (params) => ipcRenderer.invoke("pipeline:run", params),
  status: (jobDir) => ipcRenderer.invoke("pipeline:status", jobDir),
  statusForRecording: (recordingDir) => ipcRenderer.invoke("pipeline:statusForRecording", recordingDir),
  cancel: (recordingDir) => ipcRenderer.invoke("pipeline:cancel", recordingDir),
});

contextBridge.exposeInMainWorld("cloudAPI", {
  pair: (pairingCode) => ipcRenderer.invoke("cloud:pair", pairingCode),
  status: () => ipcRenderer.invoke("cloud:status"),
  disconnect: () => ipcRenderer.invoke("cloud:disconnect"),
});

contextBridge.exposeInMainWorld("scheduleAPI", {
  list: (cameraId) => ipcRenderer.invoke("schedule:list", cameraId),
  add: (cameraId, session) => ipcRenderer.invoke("schedule:add", cameraId, session),
  remove: (cameraId, sessionId) => ipcRenderer.invoke("schedule:remove", cameraId, sessionId),
  rename: (cameraId, sessionId, label) => ipcRenderer.invoke("schedule:rename", cameraId, sessionId, label),
  listAll: () => ipcRenderer.invoke("schedule:listAll"),
});
