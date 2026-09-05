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
  // No options anymore -- scanSettings.js (extra ranges + timeout) is the
  // single source of truth main.js's own handler reads internally now,
  // same pattern as getNetworkInfo() already being computed server-side.
  sweep: () => ipcRenderer.invoke("cameras:sweep"),
  probeRtspFallback: (config) => ipcRenderer.invoke("cameras:probeRtspFallback", config),
  addRtsp: (config) => ipcRenderer.invoke("cameras:addRtsp", config),
  parseRtspUrl: (raw, fallbackUsername, fallbackPassword) =>
    ipcRenderer.invoke("cameras:parseRtspUrl", raw, fallbackUsername, fallbackPassword),
  setCalibPath: (id, calibPath) => ipcRenderer.invoke("cameras:setCalibPath", id, calibPath),
  addSampleClip: (config) => ipcRenderer.invoke("cameras:addSampleClip", config),
});

contextBridge.exposeInMainWorld("scanSettingsAPI", {
  get: () => ipcRenderer.invoke("scanSettings:get"),
  addRange: (cidr) => ipcRenderer.invoke("scanSettings:addRange", cidr),
  removeRange: (cidr) => ipcRenderer.invoke("scanSettings:removeRange", cidr),
  setTimeout: (ms) => ipcRenderer.invoke("scanSettings:setTimeout", ms),
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
  status: (cameraId) => ipcRenderer.invoke("capture:status", cameraId),
  listRecordings: (cameraId) => ipcRenderer.invoke("capture:listRecordings", cameraId),
});

contextBridge.exposeInMainWorld("pipelineAPI", {
  run: (params) => ipcRenderer.invoke("pipeline:run", params),
  status: (jobDir) => ipcRenderer.invoke("pipeline:status", jobDir),
  statusForRecording: (recordingDir) => ipcRenderer.invoke("pipeline:statusForRecording", recordingDir),
  cancel: (recordingDir) => ipcRenderer.invoke("pipeline:cancel", recordingDir),
});

contextBridge.exposeInMainWorld("cloudAPI", {
  register: () => ipcRenderer.invoke("cloud:register"),
  status: () => ipcRenderer.invoke("cloud:status"),
  disconnect: () => ipcRenderer.invoke("cloud:disconnect"),
  getAgentName: () => ipcRenderer.invoke("cloud:getAgentName"),
  setAgentName: (name) => ipcRenderer.invoke("cloud:setAgentName", name),
  getDeviceId: () => ipcRenderer.invoke("cloud:getDeviceId"),
});

contextBridge.exposeInMainWorld("authAPI", {
  signIn: (email, password) => ipcRenderer.invoke("auth:signIn", email, password),
  signOut: () => ipcRenderer.invoke("auth:signOut"),
  getSession: () => ipcRenderer.invoke("auth:getSession"),
  getBrand: () => ipcRenderer.invoke("auth:getBrand"),
});

contextBridge.exposeInMainWorld("analyticsAPI", {
  capture: (event, properties) => ipcRenderer.invoke("analytics:capture", event, properties),
  isFeatureEnabled: (key) => ipcRenderer.invoke("analytics:isFeatureEnabled", key),
});

contextBridge.exposeInMainWorld("logAPI", {
  list: () => ipcRenderer.invoke("log:list"),
  clear: () => ipcRenderer.invoke("log:clear"),
});

contextBridge.exposeInMainWorld("liveViewAPI", {
  start: (cameraId) => ipcRenderer.invoke("liveview:start", cameraId),
  stop: () => ipcRenderer.invoke("liveview:stop"),
});
