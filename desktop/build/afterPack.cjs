// Strips ffprobe binaries for platforms this build will never run on.
//
// `ffprobe-static` ships every platform and architecture in one package --
// 336 MB of binaries, of which exactly one (73 MB on Apple silicon) is
// ever executed. That was over half the 490 MB DMG: each Mac build was
// carrying Windows, Linux and wrong-architecture Mac binaries.
//
// `ffmpeg-static` doesn't have this problem -- it downloads only the arch
// it was installed for, which is why the workflow does a separate `npm ci`
// per architecture. That machinery doesn't help here, because
// ffprobe-static bundles the lot regardless.
//
// afterPack, deliberately, not beforePack: beforePack would have to delete
// from the real node_modules, leaving a local build with a broken working
// tree until the next `npm install`. afterPack only touches build output
// under release/, and it runs before the DMG is assembled, so the saving
// still lands.
//
// The path is searched for rather than constructed: macOS nests resources
// inside `<app>.app/Contents/Resources` while Linux and Windows use
// `resources/`, and hardcoding either means the prune silently does
// nothing on the other.
 // .cjs, not .js: package.json sets "type": "module", so a .js hook is
// loaded as ESM and `require`/`exports` here would throw. Same reason
// electron/preload.cjs carries the extension.
const fs = require('node:fs')
const path = require('node:path')

// builder-util's Arch enum. Kept as a literal map rather than imported so
// this hook has no dependency of its own.
const ARCH_NAMES = { 0: 'ia32', 1: 'x64', 2: 'armv7l', 3: 'arm64', 4: 'universal' }

function findFfprobeBinDir(root) {
  const entries = fs.readdirSync(root, { recursive: true, withFileTypes: true })
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const full = path.join(entry.parentPath ?? entry.path, entry.name)
    if (full.endsWith(path.join('ffprobe-static', 'bin'))) return full
  }
  return null
}

function directorySize(dir) {
  let total = 0
  for (const entry of fs.readdirSync(dir, { recursive: true, withFileTypes: true })) {
    if (entry.isFile()) total += fs.statSync(path.join(entry.parentPath ?? entry.path, entry.name)).size
  }
  return total
}

exports.default = async function afterPack(context) {
  const platform = context.electronPlatformName // 'darwin' | 'win32' | 'linux'
  const arch = ARCH_NAMES[context.arch]
  const binDir = findFfprobeBinDir(context.appOutDir)

  // Not present at all: ffprobe-static was removed as a dependency, which
  // is a legitimate state (see option 3 in the size discussion). Nothing
  // to prune, and nothing to complain about.
  if (!binDir) {
    console.log('[afterPack] ffprobe-static not bundled -- nothing to prune')
    return
  }

  const keep = path.join(binDir, platform, arch)
  // Present but missing the binary this build needs: that is a real
  // problem and must stop the build. Shipping an app whose ffprobe is
  // absent breaks recording and the ADR-087 frame-rate gate at the venue,
  // silently, long after anyone is watching the build log.
  if (!fs.existsSync(keep)) {
    throw new Error(
      `[afterPack] ffprobe-static has no binary for ${platform}/${arch} ` +
        `(looked in ${binDir}). Refusing to ship a build whose ffprobe is missing.`,
    )
  }

  const before = directorySize(binDir)
  for (const platformDir of fs.readdirSync(binDir)) {
    const full = path.join(binDir, platformDir)
    if (!fs.statSync(full).isDirectory()) continue
    if (platformDir !== platform) {
      fs.rmSync(full, { recursive: true, force: true })
      continue
    }
    // Right platform, wrong architectures.
    for (const archDir of fs.readdirSync(full)) {
      if (archDir !== arch) fs.rmSync(path.join(full, archDir), { recursive: true, force: true })
    }
  }

  const after = directorySize(binDir)
  const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(0)} MB`
  console.log(
    `[afterPack] ffprobe-static pruned to ${platform}/${arch}: ${mb(before)} -> ${mb(after)} ` +
      `(saved ${mb(before - after)})`,
  )
}
