// Registers electron-stub-loader.mjs so `npm test` can import main-process
// modules that would otherwise need a real Electron runtime.
import { register } from "node:module";
import { pathToFileURL } from "node:url";

register("./electron-stub-loader.mjs", pathToFileURL(import.meta.filename));
