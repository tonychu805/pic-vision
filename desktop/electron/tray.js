// Menu bar presence, so a closed window doesn't look like a stopped agent.
//
// On macOS this app already keeps running when its window is closed --
// `window-all-closed` deliberately doesn't quit there, so the heartbeat
// keeps reporting and any ffmpeg recording keeps writing. The problem was
// that nothing SAID so: close the window and the only trace is a Dock
// icon. A venue owner can't tell whether they've stopped recording, and
// the honest answer (they haven't) is the one that matters, because they
// may well have meant to.
//
// So this is the reassurance half, not the mechanism: the icon shows the
// agent is alive, the menu shows what it's actually doing, and Quit is a
// deliberate action rather than something you do by accident with a red
// button that means "hide".
//
// Two macOS specifics worth knowing before editing:
//
//   * The icon files are named *Template.png. macOS treats a "template"
//     image as a stencil -- only the alpha channel is used, and the system
//     paints it black on a light menu bar and white on a dark one. A
//     coloured icon is legible in exactly one of the two.
//   * They live in electron/assets/, not build/. `build/` is not in
//     package.json's build.files, so anything referenced there is absent
//     from a packaged app -- which is precisely how this app once shipped
//     a build that launched with no window (ADR-090). electron/ is
//     packaged, and packaged-paths.test.js enforces the rule.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { app, Menu, Tray, nativeImage, BrowserWindow } from "electron";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Module-level, and it must stay that way: a Tray that goes out of scope
// is garbage-collected and silently vanishes from the menu bar.
let tray = null;
let refreshTimer = null;

const REFRESH_MS = 5000;

/**
 * Rebuilds the menu from live state.
 *
 * Rebuilt on a timer rather than only on open, because macOS gives no
 * reliable "menu is about to open" hook for a Tray with a context menu
 * attached -- a menu built once at startup would claim "Not recording"
 * forever.
 */
function render({ isRecordingNow, recordingLabels, connection }) {
  if (!tray) return;

  const recording = recordingLabels.length > 0;
  const connected = Boolean(connection);

  const items = [
    { label: connection?.brandName ? `picvision ai — ${connection.brandName}` : "picvision ai", enabled: false },
    { type: "separator" },
    {
      // Deliberately reports the local view only. Whether the last
      // heartbeat actually succeeded is a different question the renderer
      // can't answer either yet (PIC-92) -- claiming "Connected" on the
      // strength of a stored token would repeat that bug in a new place.
      label: connected ? `Signed in to ${connection.consoleUrl.replace(/^https?:\/\//, "")}` : "Not connected to the console",
      enabled: false,
    },
    {
      label: recording
        ? `Recording: ${recordingLabels.join(", ")}`
        : "Not recording",
      enabled: false,
    },
    { type: "separator" },
    {
      label: "Open picvision",
      click: () => {
        const [existing] = BrowserWindow.getAllWindows();
        if (existing) {
          if (existing.isMinimized()) existing.restore();
          existing.show();
          existing.focus();
        } else {
          // No window left (closed on macOS). `activate` is what main.js
          // already listens for to rebuild one, so emit that rather than
          // duplicating createWindow() here.
          app.emit("activate");
        }
      },
    },
    { type: "separator" },
    {
      // Goes through app.quit(), not app.exit(), so before-quit runs and
      // stops any recording cleanly -- ADR-031 found that killing ffmpeg
      // outright corrupts the output container.
      label: recording ? "Stop recording and quit" : "Quit picvision",
      click: () => app.quit(),
    },
  ];

  tray.setContextMenu(Menu.buildFromTemplate(items));
  tray.setToolTip(recording ? `picvision ai — recording ${recordingLabels.join(", ")}` : "picvision ai — running");

  // macOS only: text beside the menu bar icon. A recording is the one
  // state worth seeing without opening anything, since it's the one that
  // costs money and fills a disk.
  if (process.platform === "darwin") {
    tray.setTitle(recording ? " ●" : "");
  }
  void isRecordingNow;
}

/**
 * @param {() => { recordingLabels: string[], connection: object|null }} readState
 *   Supplied by main.js rather than imported here, so this module doesn't
 *   pull in capture.js/cloud.js and can't create an import cycle.
 */
export function createTray(readState) {
  if (tray) return tray;

  const icon = nativeImage.createFromPath(path.join(__dirname, "assets", "trayTemplate.png"));
  // Explicit, though the filename already implies it to macOS -- being
  // wrong here means an icon that's invisible on one menu bar theme.
  icon.setTemplateImage(true);

  try {
    tray = new Tray(icon);
  } catch (err) {
    // No system tray (a bare Linux session, some CI environments). The
    // agent is fully functional without one; this is an affordance.
    console.error(`[tray] could not create a menu bar icon: ${err.message}`);
    return null;
  }

  const refresh = () => {
    try {
      render(readState());
    } catch (err) {
      console.error(`[tray] refresh failed: ${err.message}`);
    }
  };

  refresh();
  refreshTimer = setInterval(refresh, REFRESH_MS);
  return tray;
}

export function destroyTray() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
  tray?.destroy();
  tray = null;
}
