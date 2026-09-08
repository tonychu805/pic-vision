// Locks down the electron-store JSON files and re-encrypts anything left
// plaintext by a version that predates ADR-082.
//
// Two gaps found by auditing the real files on 2026-09-07, both of the
// same shape -- the fix was applied to new writes and never to what was
// already on disk:
//
//   1. auth.json still held a plaintext Supabase access/refresh token
//      pair. auth.js has encrypted on save since 2026-09-06 01:22, but
//      that file was last written at 00:39, 43 minutes earlier, and
//      nothing rewrites it until the next sign-in. A refresh token is a
//      full account credential.
//
//   2. All the store files were mode 664 -- readable by every other user
//      account on the machine. The repo's own .env was locked to 600 the
//      day before; these were missed. Encryption makes that survivable
//      for the encrypted fields and not for the plaintext ones.
//
// The ongoing fix for (2) is `configFileMode: 0o600` at each `new Store()`
// -- see activityLog.js. What's left here is the one-time repair of files
// an older build already wrote 664, which no amount of correct future
// writing fixes on its own.
//
// Runs once at startup, before anything reads a credential.
import { chmodSync, existsSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { app } from "electron";
import { encryptField, isEncrypted } from "./secureField.js";

// Which fields in which files hold secrets. Kept as data rather than
// spread across each module's own save path, because the point here is to
// repair files those save paths never touch.
const SECRET_FIELDS = {
  "auth.json": [["session", "accessToken"], ["session", "refreshToken"]],
  "cloud.json": [["connection", "apiToken"]],
  // cameras.json holds an array, handled separately below.
};

function tighten(file) {
  try {
    // 0600: owner read/write only.
    //
    // This is REPAIR, not the mechanism. An earlier version of this file
    // claimed electron-store "offers no option to change it" and relied on
    // this chmod alone; both halves were wrong. electron-store forwards its
    // options to conf, which accepts configFileMode -- and conf writes
    // atomically (temp file, then rename), so the inode chmod-ed here is
    // thrown away by the next write. Startup would tighten activityLog.json
    // and the first camera status change seconds later would put it back to
    // 664. The stores now ask for 0600 themselves; this only catches files
    // that were on disk before that shipped.
    chmodSync(file, 0o600);
  } catch {
    // A filesystem without POSIX modes (some Windows setups). Nothing to
    // do, and not worth failing startup over.
  }
}

// A plain writeFileSync truncates in place, so a crash between truncate
// and write leaves invalid JSON -- and conf's clearInvalidConfig defaults
// to false, meaning every later read THROWS. For cameras.json that's the
// camera list and its calibration unreachable, not merely reset. Write a
// sibling temp file and rename it over: rename is atomic, so the file is
// either wholly old or wholly new. (Same approach conf itself uses via
// `atomically`, which isn't a direct dependency here.)
function writeAtomically(file, contents) {
  const temp = `${file}.${process.pid}.tmp`;
  try {
    writeFileSync(temp, contents, { mode: 0o600 });
    renameSync(temp, file);
  } catch (err) {
    try {
      unlinkSync(temp);
    } catch {
      // Nothing to clean up.
    }
    throw err;
  }
}

function reencryptFile(file, name) {
  let data;
  try {
    data = JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return 0; // unreadable or not yet written
  }

  let changed = 0;
  const fix = (obj, key) => {
    if (obj && typeof obj[key] === "string" && !isEncrypted(obj[key])) {
      const encrypted = encryptField(obj[key]);
      // encryptField returns the value unchanged when the OS vault isn't
      // available -- don't count that as a migration or we'd rewrite the
      // file on every launch for nothing.
      if (isEncrypted(encrypted)) {
        obj[key] = encrypted;
        changed++;
      }
    }
  };

  if (name === "cameras.json") {
    for (const camera of data.cameras ?? []) {
      fix(camera, "password");
      fix(camera, "streamUri");
    }
  } else {
    for (const [parent, key] of SECRET_FIELDS[name] ?? []) fix(data[parent], key);
  }

  if (changed > 0) writeAtomically(file, JSON.stringify(data, null, "\t"));
  return changed;
}

// Every file a `new Store({ name })` in electron/ creates. storeFiles.test.js
// checks this against the actual call sites, because a store added later
// would otherwise be skipped silently -- getting neither the repair chmod
// nor the plaintext migration. The list previously named a schedules.json
// that nothing has ever created, which is what prompted the test.
export const STORE_FILES = ["auth.json", "cloud.json", "cameras.json", "activityLog.json", "scanSettings.json"];

// Files an OLDER build created and nothing writes any more. They're still
// sitting in userData on every machine that ran that build -- schedules.json
// is on this developer's box, written 2026-09-03 -- so the repair pass has
// to keep reaching them even though no `new Store()` matches. Kept separate
// from STORE_FILES so the two claims stay distinct: one is "these exist
// now", the other is "these are leftovers". Removing a store from the app
// means moving its filename down here, not deleting it.
export const LEGACY_STORE_FILES = ["schedules.json"];

export function secureStoreFiles() {
  const dir = app.getPath("userData");
  let migrated = 0;

  for (const name of [...STORE_FILES, ...LEGACY_STORE_FILES]) {
    const file = path.join(dir, name);
    if (!existsSync(file)) continue;
    // Permissions first: a file about to be rewritten with re-encrypted
    // contents shouldn't be world-readable for even that moment.
    tighten(file);
    if (name in SECRET_FIELDS || name === "cameras.json") migrated += reencryptFile(file, name);
  }

  if (migrated > 0) {
    console.log(`[store] re-encrypted ${migrated} secret(s) left in plaintext by an older version`);
  }
}
