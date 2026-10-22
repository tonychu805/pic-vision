# Dependency inventory & vulnerability scan

Generated **2026-10-22** for the `pic-vision` repo.

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
> scan tooling I installed (`pip-audit`, `cyclonedx-bom`) and their unique transitive deps.
> Those are **not app runtime deps**. All flagged vulnerable packages trace to the app's own
> direct dependencies (see chains below), so the findings are unaffected.

## Summary

| Component | Total | Critical | High | Moderate | In **runtime** (ships) |
|---|---|---|---|---|---|
| Python | 29 | — (pip-audit reports no CVSS) | | | 29, all transitive |
| Desktop | 18 | 2 | 7 | 9 | **1** (rest dev/build-only) |

The desktop headline (2 critical / 7 high) is almost entirely **build-time tooling** that never
ships in the packaged app. Only **one** desktop finding is reachable at runtime.

---

## Python — 29 vulns, 4 packages (all transitive)

None of the 9 direct deps (`opencv-python`, `numpy`, `ultralytics`, `pyyaml`, `python-dotenv`,
`flask`, `boto3`, `requests`, `pytest`) is directly flagged. The hits are in transitive deps:

| Package | Ver | #Vulns | Fix | Pulled in by (direct dep) |
|---|---|---|---|---|
| **pillow** | 12.3.0 | 24 | **13.0.0** | `ultralytics` (+ matplotlib, torchvision) |
| **urllib3** | 2.7.0 | 3 | **2.8.0** | `requests`, `boto3` (botocore) |
| **werkzeug** | 3.1.8 | 1 | **3.1.9** | `flask` |
| **certifi** | 2026.7.22 | 1 | **2026.10.19** | `requests` |

Notes:
- **pillow** — all 24 CVEs are fixed by the single bump to **13.0.0**. Biggest cluster; most trace
  to the `ultralytics` torch/vision stack — which is the **retired YOLO path** (see `CLAUDE.md`
  "Pipeline state"). If `ultralytics` can be dropped from `requirements.txt`, the pillow +
  torchvision + matplotlib surface largely disappears.
- **certifi** PYSEC-2026-4320 — bundled a compromised emSign CA root; on-path cert spoofing.
  Low-effort fix, worth doing.
- **werkzeug / urllib3** — one and three advisories respectively; clean minor bumps.

### Fix
```bash
# pillow is transitive; pin an upgrade or let the resolver take it
.venv/bin/pip install -U "pillow>=13.0.0" "urllib3>=2.8.0" "werkzeug>=3.1.9" "certifi>=2026.10.19"
# then re-freeze / re-run: .venv/bin/pip-audit
```
Longer-term: evaluate removing `ultralytics` from `requirements.txt` (retired path).

---

## Desktop — 18 vulns, but only 1 ships

Running `npm audit --omit=dev` (what actually ends up in the packaged Electron app) leaves exactly
one finding. The other 17 are in the **build/dev toolchain** (`electron-builder`, `vite`,
`concurrently`, `dmg-builder`, …) — they run on the developer's machine at build time and are not
distributed.

### Runtime-reachable (1)

| Package | Ver | Severity | Chain | Fix |
|---|---|---|---|---|
| **fast-uri** | 3.1.6 | high | `electron-store → conf → ajv → fast-uri` | `>=3.1.8` (via `npm audit fix`) |

`fast-uri` is used by `ajv` to validate the **developer-defined** electron-store config schema, not
untrusted user-supplied URIs — so practical exploitability is low. Still a clean fix.

### Dev/build-only (17, not shipped)

`@electron/get`, `app-builder-lib`, `brace-expansion`, `concurrently` *(critical — shell-quote
command injection)*, `dmg-builder`, `electron`, `electron-builder`,
`electron-builder-squirrel-windows`, `follow-redirects`, `global-agent`, `http-cache-semantics`,
`joi`, `roarr`, `shell-quote` *(critical)*, `source-map-js`, `sprintf-js`, `vite`.

These are real but low-urgency: a build-tool DoS/injection requires a hostile build input on the
dev/CI machine, not a path exposed to app users.

### Fix
```bash
cd desktop
npm audit fix            # resolves fast-uri + many dev findings
# the remaining dev findings need: npm audit fix --force  (installs electron-builder@26 — BREAKING,
# so do it on a branch and rebuild + smoke-test the DMG per CLAUDE.md release gates)
```

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
