// Version comparison for the update check.
//
// Hand-rolled rather than pulling in `semver`: this compares two strings we
// produce ourselves, and every dependency in the main process is one that
// ships to every venue.
//
// No Electron imports, so it stays testable under plain `node --test` --
// the same constraint frameRate.js has, and for the same reason (ADR-087
// records what broke when that slipped).

/** "1.2.3" or "1.2.3-beta.1" -> numbers plus an optional prerelease tag. */
function parse(version) {
  if (typeof version !== "string") return null;
  const match = version.trim().replace(/^v/, "").match(/^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/);
  if (!match) return null;
  return { parts: [Number(match[1]), Number(match[2]), Number(match[3])], prerelease: match[4] ?? null };
}

/**
 * -1 if a is older, 0 if equal, 1 if a is newer.
 *
 * Returns null when either side can't be parsed, and callers must treat
 * that as "don't know" rather than as equal -- a malformed version must
 * never read as "up to date", which is the one wrong answer that costs the
 * operator something.
 */
export function compareVersions(a, b) {
  const left = parse(a);
  const right = parse(b);
  if (!left || !right) return null;

  for (let i = 0; i < 3; i++) {
    if (left.parts[i] !== right.parts[i]) return left.parts[i] < right.parts[i] ? -1 : 1;
  }

  // 1.0.0 beats 1.0.0-beta.1: a finished release outranks its own
  // prereleases. Without this, someone on the final build would be told to
  // "update" back to the beta they came from.
  if (left.prerelease === right.prerelease) return 0;
  if (left.prerelease === null) return 1;
  if (right.prerelease === null) return -1;
  return left.prerelease < right.prerelease ? -1 : left.prerelease > right.prerelease ? 1 : 0;
}

/**
 * The three states the UI can show. "unknown" is deliberately distinct
 * from "current": the console returns a null version when it couldn't
 * reach GitHub or nothing is published yet, and reporting that as up to
 * date would be a claim we haven't earned.
 */
export function updateState(currentVersion, release) {
  const base = { current: currentVersion, latest: null, downloadUrl: null, notes: null };
  if (!release || typeof release.version !== "string" || !release.url) {
    return { ...base, status: "unknown" };
  }
  const comparison = compareVersions(currentVersion, release.version);
  if (comparison === null) {
    return { ...base, status: "unknown", latest: release.version, downloadUrl: release.url };
  }
  return {
    status: comparison < 0 ? "outdated" : "current",
    current: currentVersion,
    latest: release.version,
    downloadUrl: release.url,
    notes: release.notes ?? null,
  };
}
