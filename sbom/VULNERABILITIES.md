# Dependency inventory & vulnerability scan

- **Scanned:** 2026-11-16, every component at its `main` (pic-vision `67dd5b4`, console, share app and website `main` of the same day)
- **Previous scan:** 2026-10-22 (history kept below)

## Scope

Since 2026-11-16 this file covers **all** components the operator runs, not only this repo:

| Component | Repo / path | Scanner | SBOM (CycloneDX) |
|---|---|---|---|
| Python pipeline (pod) | pic-vision `requirements.txt` (fresh resolve) | `pip-audit` 2.10.1 | `sbom-python.cdx.json` (1.4, 71) |
| Desktop app | pic-vision `desktop/` | `npm audit` (npm 10.9.9) | `sbom-desktop.cdx.json` (all, 475), `sbom-desktop-runtime.cdx.json` (ships, 46) |
| Desktop bundled runtime | Electron/Node/Chromium inside the app | Electron release notes | — (version below) |
| Console | pic-vision-cloud-console | `pnpm audit --prod` (pnpm 11.24.0) | `sbom-console-runtime.cdx.json` (1.7, 405) |
| Orchestrator worker | pic-vision-cloud-console `orchestrator-worker/` | `npm audit` | none: **0 runtime packages** (bundled by wrangler; every listed package is a build tool) |
| Share app | pic-vision-reel | `pnpm audit --prod` | `sbom-share-runtime.cdx.json` (1.7, 363) |
| Website | pic-vision-website | `pnpm audit --prod` | `sbom-website-runtime.cdx.json` (1.7, 387) |

Not covered: the pod's container image (stock PyTorch image; OS packages), Supabase, Netlify, Cloudflare and RunPod platforms.

---

## After the 2026-11-16 fixes (PRs open; SBOMs above describe this state)

| Component | Before | After | Change |
|---|---|---|---|
| Desktop — ships | 0 | 0 | Electron 44.10.0 → **44.11.3** (Node 24.22.2) |
| Desktop — build only | 4 high, 8 moderate | 6 moderate | non-breaking `npm audit fix`; electron-builder chain left (breaking, plan step 6) |
| Console (production) | 5 critical, 37 high | **0** | Next.js 16.4.6, shadcn → devDependencies, posthog-js ^1.449.2, overrides for browserslist / baseline-browser-mapping |
| Share app (production) | 4 critical, 36 high | **0** | same |
| Website (production) | 5 critical, 37 high | **0** | same |
| Orchestrator — build only | 4 high | **0** | non-breaking `npm audit fix` |
| Python | 0 | 0 | — |

The table below is the scan as found, before these fixes.

## Current status (2026-11-16)

| Component | Critical | High | Moderate | Low | Read this as |
|---|---:|---:|---:|---:|---|
| Python pipeline | 0 | 0 | 0 | 0 | clean |
| Desktop — ships | 0 | 0 | 0 | 0 | clean (npm packages) |
| Desktop — build only | 0 | 4 | 8 | 0 | never shipped; 7 have non-breaking fixes |
| **Desktop — bundled Electron** | — | — | — | — | **behind: 44.10.0, latest 44.11.3** (see below) |
| **Console** (production deps) | 5 | 37 | 50 | 14 | **Next.js 16.3.3** criticals; most of the rest via `shadcn` (build-time only) |
| Orchestrator | 0 | 0 | 0 | 0 | runtime clean; 4 high in build tools (wrangler, miniflare, sharp, undici) |
| **Share app** (production deps) | 4 | 36 | 50 | 11 | same pattern as the console |
| **Website** (production deps) | 5 | 37 | 50 | 14 | same pattern as the console |

### 1. Next.js 16.3.3 in the console, share app and website — upgrade to ≥ 16.4.1

Three **critical remote-code-execution** advisories (GitHub advisory DB via `pnpm audit`), plus eight more for `next`:

| Advisory | Affects | Fixed in | Used by our apps? |
|---|---|---|---|
| GHSA-2464-fhr4-w9xw — unauthenticated RCE in Image Optimization | 16.0.0–16.4.0 | 16.4.1 | No `next/image`; all three set `images.unoptimized: true`; on Netlify `/_next/image` goes to Netlify's image CDN |
| GHSA-673q-mjm6-r5xr — unauthenticated RCE in `use cache` | 16.0.0–16.4.0 | 16.4.1 | No `'use cache'` anywhere |
| GHSA-vcvr-r3jv-pc5j — RCE in `next/og` ImageResponse | 16.2.0–16.3.5 | 16.3.6 | No `next/og` |

So likely **not exploitable** for us (reasoned from the code, not tested), but the fix is a routine upgrade and should go first. Each app needs its own PR and a staging check.

### 2. `shadcn` is a runtime dependency but is only a build-time CSS import

All three apps list `shadcn` under `dependencies` and use it only as `@import 'shadcn/tailwind.css'`, compiled at build. It pulls in Express, the MCP SDK, undici, body-parser, proxy-addr (critical), fast-uri, ip-address, js-yaml, zod, brace-expansion… none of which runs on the live sites. Moving it to `devDependencies` removes most of the production findings above; then upgrade it (or not) as a build tool.

### 3. Console only: `dompurify` (critical) via `posthog-js`

Runs in the browser (analytics). Fixed in dompurify ≥ 3.4.17: upgrade `posthog-js` to a release that pulls it.

### 4. Desktop bundled Electron 44.10.0 → 44.11.3

`npm audit` doesn't see the Chromium/Node inside Electron. Since 44.10.0, every 44.x patch (44.10.1–44.11.3, 2026-10-31 → 11-12) backports upstream **Chromium, V8, Skia, ANGLE, PDFium, WebRTC and FFmpeg** fixes, and 44.10.2 updates Node.js to **24.22.2** (from the Electron release notes; the individual CVEs weren't looked up). Patch-level, same major: bump in the next desktop release.

### 5. Build tools only (never shipped)

- Desktop: brace-expansion, follow-redirects, joi, undici (high); eslint, @eslint/config-array, electron-builder-squirrel-windows (moderate) — `npm audit fix` (non-forced) clears these 7; electron-builder / app-builder-lib / dmg-builder / @electron/universal / minimatch still need the breaking `electron-builder` change (unchanged since 10-22, see below).
- Orchestrator: wrangler, miniflare, sharp, undici (high) — non-breaking `npm audit fix` available.

### Per-app high/critical detail (production dependencies)

#### Console

| Package | Worst | Advisories | Fixed in | Pulled in by |
|---|---|---|---|---|
| next | critical | 11 | >=16.3.6, >=16.3.8, >=16.4.1 | @vercel/analytics, next |
| dompurify | critical | 5 | >=3.4.16, >=3.4.17 | posthog-js |
| proxy-addr | critical | 1 | >=2.0.8 | shadcn |
| undici | high | 18 | >=7.29.1, >=7.30.1 | shadcn |
| fast-uri | high | 11 | >=3.1.3, >=3.1.4, >=3.1.5, >=3.1.6, >=3. | shadcn |
| ip-address | high | 8 | >=10.2.1, >=10.2.2, >=10.3.1, >=10.5.1,  | shadcn |
| @modelcontextprotocol/sdk | high | 6 | >=1.30.1, >=1.31.0, >=1.32.0 | shadcn |
| brace-expansion | high | 6 | >=5.0.10, >=5.0.11, >=5.0.12, >=5.0.7, > | shadcn |
| js-yaml | high | 3 | >=4.3.0, >=4.3.1, >=4.3.2 | shadcn |
| body-parser | high | 2 | >=2.3.0, >=2.4.0 | shadcn |
| browserslist | high | 2 | >=4.28.7 | @vercel/analytics, next, shadcn |
| sharp | high | 2 | >=0.35.4, >=0.35.5 | @vercel/analytics, next |
| nanoid | high | 1 | >=3.3.18 | @vercel/analytics, next, shadcn |
| source-map-js | high | 1 | >=1.2.2 | @vercel/analytics, next, shadcn |
| zod | high | 1 | >=4.6.6 | shadcn |

Plus 7 packages with moderate/low findings only.

#### Share app

| Package | Worst | Advisories | Fixed in | Pulled in by |
|---|---|---|---|---|
| next | critical | 11 | >=16.3.6, >=16.3.8, >=16.4.1 | next |
| proxy-addr | critical | 1 | >=2.0.8 | shadcn |
| undici | high | 18 | >=7.29.1, >=7.30.1 | shadcn |
| fast-uri | high | 11 | >=3.1.3, >=3.1.4, >=3.1.5, >=3.1.6, >=3. | shadcn |
| ip-address | high | 8 | >=10.2.1, >=10.2.2, >=10.3.1, >=10.5.1,  | shadcn |
| @modelcontextprotocol/sdk | high | 6 | >=1.30.1, >=1.31.0, >=1.32.0 | shadcn |
| brace-expansion | high | 6 | >=5.0.10, >=5.0.11, >=5.0.12, >=5.0.7, > | shadcn |
| js-yaml | high | 3 | >=4.3.0, >=4.3.1, >=4.3.2 | shadcn |
| body-parser | high | 2 | >=2.3.0, >=2.4.0 | shadcn |
| browserslist | high | 2 | >=4.28.7 | next, shadcn |
| sharp | high | 2 | >=0.35.4, >=0.35.5 | next |
| nanoid | high | 1 | >=3.3.18 | next, shadcn |
| source-map-js | high | 1 | >=1.2.2 | next, shadcn |
| zod | high | 1 | >=4.6.6 | shadcn |

Plus 7 packages with moderate/low findings only.

#### Website

| Package | Worst | Advisories | Fixed in | Pulled in by |
|---|---|---|---|---|
| next | critical | 11 | >=16.3.6, >=16.3.8, >=16.4.1 | next |
| dompurify | critical | 5 | >=3.4.16, >=3.4.17 | posthog-js |
| proxy-addr | critical | 1 | >=2.0.8 | shadcn |
| undici | high | 18 | >=7.29.1, >=7.30.1 | shadcn |
| fast-uri | high | 11 | >=3.1.3, >=3.1.4, >=3.1.5, >=3.1.6, >=3. | shadcn |
| ip-address | high | 8 | >=10.2.1, >=10.2.2, >=10.3.1, >=10.5.1,  | shadcn |
| @modelcontextprotocol/sdk | high | 6 | >=1.30.1, >=1.31.0, >=1.32.0 | shadcn |
| brace-expansion | high | 6 | >=5.0.10, >=5.0.11, >=5.0.12, >=5.0.7, > | shadcn |
| js-yaml | high | 3 | >=4.3.0, >=4.3.1, >=4.3.2 | shadcn |
| body-parser | high | 2 | >=2.3.0, >=2.4.0 | shadcn |
| browserslist | high | 2 | >=4.28.7 | next, shadcn |
| sharp | high | 2 | >=0.35.4, >=0.35.5 | next |
| nanoid | high | 1 | >=3.3.18 | next, shadcn |
| source-map-js | high | 1 | >=1.2.2 | next, shadcn |
| zod | high | 1 | >=4.6.6 | shadcn |

Plus 7 packages with moderate/low findings only.


---

# History

### Remediation applied (2026-10-22)

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

### Still open — desktop dev/build toolchain only (no clean fix yet; do NOT --force)

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

### Fixed — Electron-bundled Node.js runtime (opened 2026-10-22, fixed 2026-10-29)

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
# Python (fresh resolve of requirements.txt, i.e. what a pod installs)
.venv/bin/pip-audit -r requirements.txt
.venv/bin/pip-audit -r requirements.txt -f cyclonedx-json -o sbom/sbom-python.cdx.json

# Desktop
cd desktop
npm audit --json                                      # all
npm audit --omit=dev --json                           # runtime only
npm sbom --sbom-format cyclonedx > ../sbom/sbom-desktop.cdx.json
npm sbom --sbom-format cyclonedx --omit dev > ../sbom/sbom-desktop-runtime.cdx.json

# Console, share app, website (each repo, after pnpm install --frozen-lockfile)
pnpm audit --prod --json
pnpm sbom --sbom-format cyclonedx --prod > <pic-vision>/sbom/sbom-<console|share|website>-runtime.cdx.json

# Orchestrator (pic-vision-cloud-console/orchestrator-worker): npm audit; no runtime packages, so no SBOM
```

> **Manual post-generation step (don't skip on regen):** `npm sbom` lists npm packages only, **not**
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
