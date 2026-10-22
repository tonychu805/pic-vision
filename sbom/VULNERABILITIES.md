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

Python test suite: **262 passed** (incl. the detection-regression gate — detector output unchanged).
Desktop suite: **lint + 341 tests passed**.

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

Longer-term: `ultralytics` is the **retired YOLO path** (`CLAUDE.md`, Pipeline state). Removing it from
`requirements.txt` would drop the pillow/torchvision/matplotlib surface entirely — then the `pillow`
floor line here can go too.
