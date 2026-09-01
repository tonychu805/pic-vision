import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" -- production build is loaded via win.loadFile() (file://),
// not a webserver, so asset URLs must be relative.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: true, // reachable over Tailscale/LAN for remote viewing during dev
  },
});
