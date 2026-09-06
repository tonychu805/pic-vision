// A Node module loader that stubs the two things only Electron provides, so
// the real main-process module graph can be imported outside Electron.
//
// Exists because the unit tests could otherwise only cover modules that
// avoid Electron entirely, which is almost none of them -- and that gap was
// real: an edit once removed six exports from capture.js and broke the app
// completely while `node --check` still passed, because a missing export is
// only an error at import time.
//
// The stubs are deliberately minimal: enough shape for a module to finish
// loading, nothing more. This proves modules *load*, not that they work --
// behaviour is covered by the unit tests around pure logic.
export async function resolve(spec, ctx, next) {
  if (spec === "electron" || spec === "electron-store") {
    return { url: "stub:" + spec, shortCircuit: true };
  }
  return next(spec, ctx);
}

export async function load(url, ctx, next) {
  if (url === "stub:electron") {
    return { format: "module", shortCircuit: true, source: `
      export const app = {
        isPackaged: false, getPath: () => "/tmp", dock: { setIcon() {} },
        on() {}, quit() {}, exit() {},
        // Never resolves on purpose. This harness checks that modules parse
        // and link, not that the app boots -- resolving here would run
        // main.js's whole startup path (windows, IPC registration, the
        // heartbeat loop) against stubs, testing nothing real and failing
        // on the first method the stub doesn't have.
        whenReady: () => new Promise(() => {}),
      };
      export const ipcMain = { handle() {} };
      export const powerSaveBlocker = { start: () => 0, stop() {} };
      export const safeStorage = {
        isEncryptionAvailable: () => false,
        encryptString: (s) => Buffer.from(s),
        decryptString: (b) => b.toString(),
      };
      export const BrowserWindow = class {
        loadURL() {} loadFile() {} on() {}
        static getFocusedWindow() { return null }
        static getAllWindows() { return [] }
      };
      export const dialog = { showOpenDialog: () => Promise.resolve({ canceled: true, filePaths: [] }) };
      export const shell = { openExternal: () => Promise.resolve() };
    ` };
  }
  if (url === "stub:electron-store") {
    return { format: "module", shortCircuit: true, source: `
      export default class Store {
        constructor() { this.data = {} }
        get(key, fallback) { return this.data[key] ?? fallback }
        set(key, value) { this.data[key] = value }
        delete(key) { delete this.data[key] }
      }
    ` };
  }
  return next(url, ctx);
}
