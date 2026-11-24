// Replacing a file by rename, retried for the moment Windows holds it.
//
// On Windows a rename over an existing file fails with EPERM, EACCES or
// EBUSY while anything else has that file open -- Defender or the search
// indexer scanning a file that was written a millisecond ago is enough.
// PGC's venue PC (2026-11-24) hit it repeatedly on cloud_job/status.json,
// which this app rewrites throughout every upload; the throw escaped from
// inside the upload stream and stalled the transfer. The same retry is what
// graceful-fs does for fs.rename on Windows.
import { renameSync } from "node:fs";

const TRANSIENT = new Set(["EPERM", "EACCES", "EBUSY"]);
const pause = new Int32Array(new SharedArrayBuffer(4));

export function renameWithRetry(from, to, { rename = renameSync, attempts = 10, waitMs = 20 } = {}) {
  for (let i = 1; ; i++) {
    try {
      return rename(from, to);
    } catch (err) {
      if (!TRANSIENT.has(err.code) || i >= attempts) throw err;
      Atomics.wait(pause, 0, 0, waitMs * i);
    }
  }
}
