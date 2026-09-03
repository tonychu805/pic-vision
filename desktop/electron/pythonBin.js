// Resolves which python3 to spawn for the repo's Python subprocesses
// (calibration.js's save_calibration.py, pipeline.js's run_desktop_job.py).
// A bare "python3" resolves to whatever's on the *Electron process's* PATH
// -- the system interpreter when the app isn't launched from a shell that
// activated the repo's .venv, which lacks cv2/numpy/boto3 and fails with
// "No module named 'cv2'" before the subprocess does anything. Falls back
// to bare "python3" if .venv isn't there (e.g. a dev machine that installed
// deps globally instead), same as before this existed.
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..", "..");
const VENV_PYTHON = path.join(REPO_ROOT, ".venv", "bin", "python3");

export const PYTHON_BIN = existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3";
