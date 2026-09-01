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
  testConnection: (config) => ipcRenderer.invoke("cameras:testConnection", config),
  sweep: (options) => ipcRenderer.invoke("cameras:sweep", options),
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
});
