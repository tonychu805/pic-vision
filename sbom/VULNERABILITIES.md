# Dependency inventory & vulnerability scan

- **Scanned:** 2026-10-22
- **Safe fixes applied:** 2026-10-22 (this branch)

## Scope

Covers the dependencies **this repo tracks**:

| Component | Manifest | Scanner | SBOM |
|---|---|---|---|
| Python pipeline | `requirements.txt` (resolved in `.venv`, Python 3.14.4) | `pip-audit` 2.10.1 (OSV + PyPI advisory DB) | `sbom-python.cdx.json` |
| Desktop app (`desktop/`) | `package-lock.json` | `npm audit` (npm 9.2.0) | `sbom-desktop.cdx.json` (all), `sbom-desktop-runtime.cdx.json` (ships) |

SBOMs are **CycloneDX 1.6 JSON**.

**Out of scope** (separate git repos / vendored third-party — each needs its own SBOM in its own tree):
`reel-page/`, `pic-vision-cloud-console/`, and the vendored `cvat/`.

> Note: `sbom-python.cdx.json` is generated from the live `.venv`, which also contains the
> scan tooling (`pip-audit`, `cyclonedx-bom`) and their unique transitive deps. Those are **not
> app runtime deps**. All flagged packages trace to the app's own direct deps (chains below).

---

## Current status (after fixes)

| Component | Before | After | Remaining |
|---|---|---|---|
| **Python** | 29 (4 pkgs, all transitive) | **0** | none |
| **Desktop — runtime (ships)** | 1 (fast-uri, high) | **0** | none |
| **Desktop — dev/build only** | 17 | **8** | 8 moderate + 1 high, all build-time; need the breaking `electron-builder@26` bump (see below) |
| **Desktop — bundled Node runtime** | 4 high (Electron 44.9.3 / Node 24.22.0) | **0** | none: Electron 44.10.0 / Node 24.22.1, desktop v1.10.3 (2026-10-29) — see "Electron-bundled Node.js runtime" below |

> `npm audit` scans JS packages only, **not** the Node/Chromium binaries Electron bundles. The
> bundled-runtime row is tracked separately (added 2026-10-22) and does not show up in the SBOMs above.

Python test suite: **262 passed** (incl. the detection-regression gate — detector output unchanged).
Desktop suite: **lint + 360 tests passed** (2026-10-29, Electron 44.10.0).

---

## Remediation applied (2026-10-22)

**Python** — added security floors to `requirements.txt` for the vulnerable transitive deps and
upgraded the `.venv`. Resolver accepted all four with no conflicts (pillow 13 coexists with
ultralytics). `pip-audit` now reports no known vulnerabilities.

| Package | 12.x → fixed | #Vulns cleared | Pulled in by |
|---|---|---|---|
| pillow | 12.3.0 → **13.0.0** | 24 | `ultralytics` (+ torchvision, matplotlib) |
| urllib3 | 2.7.0 → **2.8.0** | 3 | `requests`, `boto3` |
| werkzeug | 3.1.8 → **3.1.9** | 1 | `flask` |
| certifi | 2026.7.22 → **2026.10.19** | 1 | `requests` (compromised emSign CA root) |

**Desktop** — ran `npm audit fix` (non-forced; `package.json` unchanged, only `package-lock.json`
transitive bumps). This cleared the one runtime finding and 9 dev findings.

| Package | Fixed | Note |
|---|---|---|
| fast-uri | 3.1.6 → **3.1.9** | runtime (via `electron-store → conf → ajv`); the only shipped vuln — now gone |

---

## Still open — desktop dev/build toolchain only (no clean fix yet; do NOT --force)

The remaining 9 desktop findings (8 moderate + 1 high) are all in build/dev tooling — almost all one
cluster inside `electron-builder`'s own dependency subtree (`app-builder-lib`, `dmg-builder`,
`@electron/get`, `…-squirrel-windows`, and `global-agent → roarr → sprintf-js`), plus `brace-expansion`.
This tooling **runs on the dev/CI machine at build time and is not distributed** in the packaged app.

**There is no clean upstream fix available.** The vulnerable sub-deps are pinned inside
`electron-builder` 26.x's dependency ranges, so nothing swaps them within range. `npm audit fix --force`
does **not** upgrade — it would **downgrade** `electron-builder` from the installed **26.18.0** to
**26.5.0** (npm mislabels this `isSemVerMajor` / "breaking"), which is older and would not even clear
the advisories. `brace-expansion` shows "fix available" but a plain `npm audit fix` does not actually
clear it (multiple nested copies pinned by parents).

**Action:** leave them as-is; do not run `--force`. Re-run `npm audit` periodically and pick up the fix
when a newer `electron-builder` release ships a patched subtree — that will be a normal in-range update,
no force. If it ever does cross a major, do it on its own branch with a **full DMG rebuild +
installed-artifact smoke test** per `CLAUDE.md` "Delivery and release gates".

---

## Fixed — Electron-bundled Node.js runtime (opened 2026-10-22, fixed 2026-10-29)

Node.js shipped security releases on **2026-10-21** (10 CVEs, 4 high). The desktop app ships
**Electron 44.9.3**, which bundles **Node 24.22.0** — affected by all four high-severity CVEs.
This is separate from `npm audit` (JS packages only) and from the SBOMs.

| CVE | Type | Node lines | Reachable in our app? |
|---|---|---|---|
| CVE-2026-111497 | Brotli decoder out-of-bounds write → possible RCE | 22.x / 24.x / 26.x | **Yes — a real path.** Main-process `fetch()` auto-decodes `br` responses; `electron/cameras/ssdp.js` fetches a LAN-advertised device-description URL and `electron/main.js` the update feed, so a hostile Brotli body is reachable from a LAN device or feed MITM. Needs a crafted stream; no known exploit, not on CISA KEV. |
| CVE-2026-106069 | TLS cert hostname bypass (host loosely resolves to IP) | 22.x / 24.x / 26.x | Low — our TLS targets (Supabase, console) use real hostnames; LAN camera traffic is mostly plain HTTP. |
| CVE-2026-105483 | TLS certificate bypass | 24.x / 26.x only | Low — same as above (note: applies to us; 24.x is affected). |
| CVE-2026-105482 | `dns.resolve` truncates names containing a NUL char | 22.x / 24.x / 26.x | Very low — no untrusted names reach `dns.resolve`. |

**Fixed in Node 24.22.1** (also 22.23.4 / 26.12.1). **Electron 44.10.0** (stable, 2026-10-28) bundles
Node 24.22.1 and Chromium 152.0.7977.169, with no breaking changes in its notes.

**Fix (2026-10-29, desktop v1.10.3):** `electron` bumped in range to `^44.10.0` (installed 44.10.0).
Evidence:
- the installed binary reports
  `{"electron":"44.10.0","node":"24.22.1","chrome":"152.0.7977.169"}`
  (`ELECTRON_RUN_AS_NODE=1 electron -e 'process.versions'`);
- desktop `npm test` 360/360; `npm audit --omit=dev` 0;
- a local package build succeeds;
- SBOMs regenerated, with the bundled runtime components updated to the new versions.

The installed-artifact gate is the v1.10.3 DMG from CI, installed on the operator's MacBook: it must
launch, pair and record. On this Linux workstation the unpacked Linux build hung at startup before
any window (it is not a shipped target; whether 44.9.3 behaves the same here was not checked).

**Also:** CI (`setup-node@v4`, `node-version: 22`) auto-resolves to ≥ 22.23.4 on its next run; the dev
machine should update local Node to 22.23.4 (build-time only). The cloud **console** (Next.js) and
**reel-page** are separate repos on their own Node runtimes — check their exposure in their own trees.

Sources: Node.js 2026-10-21 security releases (nodejs.org/en/blog/vulnerability/october-2026-security-releases);
Electron stable releases (releases.electronjs.org).

---

## Regenerate

```bash
# Python
.venv/bin/pip-audit                                   # vuln scan
.venv/bin/cyclonedx-py environment .venv --of JSON -o sbom/sbom-python.cdx.json

# Desktop
cd desktop
npm audit --json                                      # all
npm audit --omit=dev --json                           # runtime only
npx @cyclonedx/cyclonedx-npm --output-format JSON --spec-version 1.6 --output-file ../sbom/sbom-desktop.cdx.json
npx @cyclonedx/cyclonedx-npm --omit dev --output-format JSON --spec-version 1.6 --output-file ../sbom/sbom-desktop-runtime.cdx.json
```

> **Manual post-generation step (don't skip on regen):** `cyclonedx-npm` lists npm packages only, **not**
> the Node/Chromium binaries Electron bundles and ships. After regenerating the two desktop SBOMs, re-add
> the bundled runtime as `platform` components (carrying a CPE so scanners can match CVEs against them):
> **Node.js** (`cpe:2.3:a:nodejs:node.js:<ver>`) and **Chromium** (`cpe:2.3:a:google:chrome:<ver>`), both
> marked `picvision:runtime:addedManually=true`, edged under `electron@<ver>` in `sbom-desktop.cdx.json`
> and under the app root in `sbom-desktop-runtime.cdx.json` (electron is dev-scoped, so absent there).
> Get the versions for the installed Electron from <https://releases.electronjs.org/release/v44.10.0>
> (currently Node 24.22.1, Chromium 152.0.7977.169). When you bump Electron, update these two versions.

Longer-term: `ultralytics` is the **retired YOLO path** (`CLAUDE.md`, Pipeline state). Removing it from
`requirements.txt` would drop the pillow/torchvision/matplotlib surface entirely — then the `pillow`
floor line here can go too.
