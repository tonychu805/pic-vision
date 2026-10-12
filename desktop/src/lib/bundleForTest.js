// Bundles one component for the render tests (esbuild, then react-dom/server).
// Uses esbuild's JS API rather than spawning node_modules/.bin/esbuild: on
// Windows that shim is a .cmd file, which an extensionless spawn can't find
// (status null) and which modern Node refuses to spawn without a shell.
import { buildSync } from "esbuild";

export function bundleForTest(entry, outfile) {
  buildSync({
    entryPoints: [entry],
    bundle: true,
    format: "esm",
    jsx: "automatic",
    external: ["react", "react-dom"],
    outfile,
    logLevel: "error",
  });
}
