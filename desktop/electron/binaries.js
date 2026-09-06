// Resolves the ffmpeg/ffprobe binaries this app spawns.
//
// These used to be the bare strings "ffmpeg"/"ffprobe", resolved off the
// Electron process's PATH. That works when the app is launched from a
// shell, and breaks the moment it's a packaged .app launched from Finder:
// macOS gives a GUI app a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin)
// with no /opt/homebrew/bin, so a Homebrew ffmpeg is invisible and every
// recording/live-view/snapshot fails with ENOENT. A venue's Mac may well
// have no ffmpeg installed at all, so the binaries ship inside the bundle
// (ffmpeg-static/ffprobe-static, asarUnpack'd in package.json's build
// config -- a binary inside app.asar can't be executed, only read).
import { app } from "electron";
import ffmpegStatic from "ffmpeg-static";
import ffprobeStatic from "ffprobe-static";

function unpacked(p) {
  // electron-builder writes asarUnpack'd files to app.asar.unpacked/, but
  // the module still reports the app.asar path it was resolved from.
  return app.isPackaged ? p.replace("app.asar", "app.asar.unpacked") : p;
}

export const FFMPEG = unpacked(ffmpegStatic);
export const FFPROBE = unpacked(ffprobeStatic.path);
