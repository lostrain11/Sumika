# Sumika Windows launcher and release gate

Latest current-source internal candidate: `product-candidate-20260920-k`, 26,229 files.
Current-host archive/install/EXE acceptance passed:
`.sumika-next/package/packaged-install-93f1d18bdb564c58b44810cd20bfd718/report.json`.
ZIP SHA-256: `570d185ce03007a1e22cf1938fc09d1f23abf159a65b0f1a7566196cbd926ad5`.
The archive has its corrected installer and internal-use README beside it.
Candidate J passed clean Windows Sandbox installation/inventory and EXE lifecycle;
K was not independently run in that guest. `candidate-k-delta.json` confirms K's
business/UI/runtime/launcher bytes are unchanged; changes are verification tools
and dependency notices only. No daily installation/data was replaced. Native
redistribution findings and explicitly deferred voice hardware remain open.

## Dependency notice inventory

`tools/audit_package_licenses.py <candidate> --output <new-report.json>` inventories
actual installed npm package roots and Python distribution metadata after package
integrity verification. It hashes declarations and notice files and identifies
README license candidates without automatically clearing license obligations.
Candidate-e evidence: `.sumika-next/package/license-audit-candidate-e-reviewed.json`.
500 npm packages and 2 Python distributions were found. Eight packages lack a
detected package notice file; `data-uri-to-buffer` includes MIT text in its README.
`@img/sharp-win32-x64` additionally declares LGPL and lists bundled native
components in `versions.json`; those components need separate terms/source review.
This evidence does not cover every component inside Node, Python, .NET or other
native executables and is not redistribution approval. Keep local development
acceptance separate from this outstanding public-release gate.

### Exit codes and the `--fail-on-findings` release gate

`main()` returns an integer and the script entry propagates it through
`SystemExit`, so the process status is directly usable by CI.

| Invocation | Exit code |
| --- | --- |
| `audit_package_licenses.py <candidate> --output <new-report.json>` | `0` whenever the inventory completes, **even when findings exist** |
| same, plus `--fail-on-findings`, no dependency findings | `0` |
| same, plus `--fail-on-findings`, one or more dependency findings | `2` |

`--fail-on-findings` is a release-audit gate and nothing more. Order of work is
fixed so a failing run still leaves usable evidence: the complete report is
written first, and only then is the exit code decided. A gate failure therefore
never costs the operator the inventory that explains it. "Findings" means any
dependency row carrying a non-empty `findings` list; these entries are review
priorities, so a code `2` reports *unreviewed obligations*, not proven violations.

The default invocation deliberately returns `0` with findings present. That
default is an inventory, never legal clearance: exit `0` means "the inventory was
produced", not "the licenses were approved". Passing the flag changes what the
process asserts, not what the tool knows, so a clean `0` from the gate still
remains subject to all the limitations in the paragraph above.

Output creation stays exclusive in every mode. An existing `--output` path raises
`ValueError` before the candidate is scanned, so a previous audit is never
overwritten or truncated — retain prior reports as evidence and choose a new path.

Status: **not release-ready**. The existing `Sumika-portable-v2.zip` contains
`.sumika-next` runtime data and has not passed clean extraction/startup in an
isolated user environment. Do not distribute or install it as a release.
Existing archives and failed staging remain preserved for inspection.

## Existing assets

Reuse `Sumika.Launcher.csproj` and `Program.cs` for the single-file Windows
launcher; reuse `tools/start_sumika.ps1` and `tools/start_ui_bridge.ps1` for
startup. The launcher is not a complete bundled Python/Node distribution.
The current internal candidate bundles Python/Node and uses explicit personal
data isolation and instance identity checks. Optional audio/OCR/office runtimes
remain separate; clean-machine acceptance is still outstanding.

```powershell
dotnet publish packaging/Sumika.Launcher.csproj -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -o .sumika-next/package/sumika-launcher
```

The original launcher smoke test used a replacement startup script. Subsequent
candidate-d acceptance exercised actual installation and full EXE startup on the
current host (see evidence below); that does not prove clean-machine startup.

## Extracted inventory verification

`tools/verify_portable_staging.py` now requires a schema version 2 manifest:

```json
{
  "kind": "portable-staging",
  "schema_version": 2,
  "files": [
    {"path": "Sumika.exe", "size": 123, "sha256": "<64 lowercase hex digits>"}
  ]
}
```

Inventory every file except `package-manifest.json` itself, using normalized
relative paths. The verifier checks exact file membership, sizes and SHA-256;
rejects unsafe paths, case aliases, filesystem links, known runtime/credential
file locations, and missing mandatory startup files. Publication must stage a
physical dependency tree rather than silently following development junctions.
Do not rewrite an old manifest simply to obtain a pass: rebuild a clean staging
tree from an explicit release selection first.

```powershell
python -B tools/verify_portable_staging.py D:/Apps/Sumika-staging
python -B -m unittest tests_next.test_portable_inventory
```

A successful result says `inventory_verified`, not release-ready. This gate
cannot identify credentials hidden in arbitrary source text, prove dependency
completeness, or verify licenses. Those reviews and isolated clean startup,
user data backup/restore, upgrade failure recovery and real development tasks
remain separate required acceptance work. Model weights and personal data
must remain outside the release.

## Installer boundaries

`install_sumika.ps1` requires a SHA-256, rejects unsafe ZIP paths, links,
duplicate entries and non-release roots, stages beside the destination rather
than in C: TEMP, and preserves failed staging. `-WhatIf` performs no writes.
The installer validates the schema version 2 inventory directly from ZIP streams
before extraction: exact membership, required startup files, sizes and SHA-256.
It does not execute code from the package or depend on Python for verification.
Fourteen synthetic checks passed through `tools/verify_portable_installer.py`,
including same-size tampering, undeclared/missing files, duplicate inventory,
nested runtime data and credentials. Invalid inventory creates no staging or
destination directory. Evidence: `.sumika-next/package/installer-check-8d0600de0e75468393164437d78ff48a/report.json`.
These checks do not certify dependencies or clean-machine startup. No approved
replacement archive is currently available. Signing is not the only remaining work.

## Physical DSH runtime candidate

A fresh isolated directory containing copies of the existing runtime package.json,
pnpm-lock.yaml and release.json was populated with pnpm 11.19.0:

```powershell
pnpm.cmd install --offline --frozen-lockfile --ignore-scripts --node-linker=hoisted
```

Run only in a new staging directory, never against the daily runtime. The local
D: pnpm store supplied all packages with zero downloads. Candidate:
`.sumika-next/package/runtime-build-4495d8c18ec9409db56879350af232c7`.
Observed 24,450 files / 222,021,483 bytes / zero filesystem links; all four
existing release hashes match. Paths also pass the inventory path policy.

`tools/verify_portable_dsh.py <candidate>` copies the runtime to a new product
root and runs real DSH against a deterministic loopback model. Native write,
edit, read and PowerShell output validation passed; owned process exit verified.
Evidence: `.sumika-next/package/runtime-relocation-503179a4ee8446f7abad328d939b760e/report.json`.
This confirms that tested native operations tolerate runtime relocation; host
Python/Node are still required and full Sumika distribution is not yet accepted.

## Python/Node baseline candidate

`tools/build_host_runtimes.py` reuses local installed Windows Python 3.14.7
and Node 24.19.0 with their licenses, copies standard-library assets only,
and pins tzdata 2025.2 plus websocket-client 1.9.2. No downloads or model
weights. Candidate `.sumika-next/package/host-runtimes-20260911-c` passed
SQLite/SSL/ctypes/timezone/WebSocket imports and hostile PYTHONPATH/PYTHONHOME
isolation. See its `isolation-evidence.json`. Earlier a/b fixtures are retained.

Use Windows backslashes in python314._pth: forward-slash ../.. resolved to
the wrong parent in this interpreter; the builder asserts the actual product
root appears in sys.path. _pth sets isolated/no_site/ignore_environment;
no_user_site alone is not a valid isolation assertion here. Optional capability
dependencies are not bundled by this baseline. Local binary copying does not
establish independently verified vendor provenance or complete product readiness.

## Startup/data wiring

The launchers accept `-DataDirectory <absolute path>` and pass its resolved
value as `SUMIKA_DATA_DIR`. Python rejects a blank/relative explicit override.
Settings, roles, schedules, browser grants and versioned DSH profiles use this
data root; no existing data is migrated. With no override a development checkout
keeps its legacy DSH profile. Packaged startup selects the personal Sumika data
directory for its DSH profiles as well. Logs now live under personal data/logs.

The bridge chooses runtime/python/python.exe and DSH chooses runtime/node/node.exe
when bundled directories exist. Incomplete bundled directories fail rather
than falling back to host interpreters. Development checkouts without those
directories still use PATH. 47 related tests passed; additional portable Node
selection coverage brings the focused portable path suite to 4 passing tests.
PowerShell syntax checks passed. Assembled-product launch and robust existing
bridge identity are still pending; arbitrary HTTP 200 is not sufficient identity.

## Assembled internal candidate

`tools/build_portable_staging.py` assembles product source/assets, the physical
DSH dependency tree, isolated Python/Node and existing BrowserSkill runtime,
then writes and verifies schema-v2 file hashes. It refuses existing targets
and filesystem links. Candidate `.sumika-next/package/product-candidate-20260911-a`
has 26,013 inventoried files. It is an internal test candidate, not a release.

`tools/verify_portable_startup.py <candidate>` passed with bundled Python:
HTML/state responses and new personal data outside installation. Evidence:
`.sumika-next/package/startup-3a2d9c3ad58c49dc903728b2583391c6/report.json`.
A separate bundled-Python WorkbenchController probe started Sumika extensions
and DSH with bundled Node, used the isolated data profile and stopped cleanly:
`.sumika-next/package/workbench-startup-8535ee7608c4420ba660b12bee48e8d4/result.json`.
Neither probe exercises the actual EXE/PowerShell launcher nor proves clean-machine
capabilities, permission UI, license readiness or real model development quality.

## Bridge identity verification

The launcher now uses ui.bridge_probe instead of accepting arbitrary HTTP 200.
It checks canonical product/settings paths, PID creation time and actual listening
port owner. Refused connection means available; unknown/occupied instances fail
closed without stopping them. /api/instance uses existing bridge read protections.
21 probe/UI tests and a real isolated matching/wrong-profile probe passed:
.sumika-next/package/bridge-identity-dbfff271196941968c11dbd45fc67d32/report.json.
Candidate a predates this change. Rebuild and EXE acceptance, plus concurrent
bridge launch single-writer protection, remain pending.

## Bridge data single writer

ui.server.serve now acquires an OS byte-range lock in the settings directory
before initializing business data. A different port does not bypass the lock.
Normal server close and process termination release it; the lock file remains
and is not an unknown-state marker. DSH child-process fencing continues to use
the existing ProfileLease separately. Constructor failures release the bridge
lock. 24 related lease/UI/identity tests passed. This does not prove graceful
shutdown of active role requests or the complete EXE lifecycle.

## Actual EXE startup acceptance

Candidate `.sumika-next/package/product-candidate-20260911-c` includes the
bridge lock, identity probe and 5-second Windows connection-refusal probe fix.
Its 26,016-file inventory passed. `tools/verify_portable_exe.py <candidate>`
passed first EXE startup through PowerShell/bundled Python, same-process reuse,
and refusal of a foreign HTTP200 listener without stopping it. The isolated
bridge was terminated only after PID/creation identity verification. Evidence:
`.sumika-next/package/exe-startup-083b1425c8464988b741e42f11bd7f03/report.json`.

An initial candidate-b failure was traced to Windows loopback connection refusal
taking ~2.02 seconds; a 1-second probe incorrectly returned unknown. Five seconds
allows refusal to be classified while actual timeouts still fail closed.
This is current-host startup acceptance, not clean-machine validation, graceful
active-task shutdown, dependency/license completeness or real model development.

## Outstanding release audit findings

Historical findings included BrowserSkill updater residuals and missing bundled
asset notices. The explicit selection and pinned notices described below address
those findings. Full transitive dependency/license review and remote binary
provenance remain outstanding; notice inclusion alone is not complete acceptance.

## Notice/selection follow-up

Builder now selects only bsk.exe and explicitly named LICENSE/NOTICE files from
BrowserSkill; .update-* residuals are also rejected by staging verifier and installer.
No source residuals were deleted. Nine inventory tests and fifteen PowerShell
installer scenarios passed (installer-check-90c75382679d4bf88607dd36ef8d5b79).
Candidate c predates this change and remains an internal test artifact.

packaging/notices contains official three-vrm v3.5.5 MIT text, current Three.js
MIT text and full VRoid sample terms HTML. sources.json records URLs and hashes;
the builder includes them under licenses/. Bundled three.js exact version is
not yet proven; this capture is not a completed transitive license audit. Actual
VRM/thumbnail hashes exposed reversed labels in the project asset document, now
corrected. BrowserSkill provenance/notice verification remains outstanding.

## Pinned notice and asset follow-up

Three.js notice now uses r185, matching the bundled window.__THREE__ marker. BrowserSkill MIT notice is pinned to cli-v0.1.11 commit 70b851a3e8408f4994a757e47137ef515bd82901. The installed executable matches the existing local release ZIP entry; a remote asset digest was unavailable due to GitHub API rate limiting, so vendor binary provenance is not fully verified.

reviewed-assets.json pins the selected executable, renderer, VRM and thumbnail; staging checks these and notice hashes before copying. Ten inventory tests passed, including rejection of changed reviewed binaries. This is a drift guard, not a complete transitive license or supply-chain audit. Candidate c is stale and must not be distributed as a release.

## Candidate d archive/install acceptance

product-candidate-20260911-d includes updated notices/BrowserSkill selection and recovery/path fixes. Its 26,020-file inventory passed. Reusable tools/verify_packaged_install.py combines existing staging verification, actual PowerShell installer and actual EXE acceptance, with all artifacts retained under the candidate parent.

Evidence: .sumika-next/package/packaged-install-33addfbf832e42d29c011a9f6ab39ce8/report.json. ZIP size 221867262 bytes, SHA-256 fdf028736860a15009c46ae5099dd9721a75cb288725266b5cbd51ff029a4b82. Archived hashes, isolated installation, installed inventory, EXE startup/reuse/foreign-port refusal and verified test-process termination passed. Ten inventory tests also passed. No shortcut or daily service was replaced.

Still INTERNAL: current Windows host only, no real model development task, not full optional dependencies/license readiness or graceful shutdown under active tasks. Original archives remain preserved.

## Windows filename parity

Reviewed real-model candidate validation was adopted into the Python verifier, with additional main-agent coverage for superscript COM/LPT digits and CONIN$/CONOUT$. The PowerShell installer now uses matching invalid-character and device-name rejection. Eleven inventory tests passed; installer-check-84ce513ddc664a8b862d1cc1d2ba88ce contains the original fifteen scenarios plus nine filename refusals and successful valid Unicode/similar-name extraction. Control-character ZIP rejection wording differs on the current PowerShell, so tests assert refusal and no staging, with exact output retained. All 26,020 candidate-d paths pass the new path rules, but the existing candidate archive predates this source change.

## Explicit retained-version recovery evidence

Candidate f restored a pre-change DSH profile; retained candidate e then opened a fresh restoration of the same snapshot. History, tool records and installation-specific plugin bindings survived with no task replay, and candidate data stayed unchanged. Evidence: `.sumika-next/package/profile-restore-7afc512933e34ff1bfada20340f08af5/report.json`. This covers explicit snapshot recovery only; failed/interrupted update and clean-machine acceptance remain pending.

## Installer extraction interruption and explicit retry

The existing `tools/verify_portable_installer.py` now stops its owned real PowerShell installer after observing the first extracted file. With a bounded synthetic archive, the incomplete destination was never published; explicit retry completed exactly; failed staging, the old installation and separate personal-data sentinel remained unchanged. Existing manifest/path/hash checks also passed. Evidence: `.sumika-next/package/installer-check-94726bd1bf66439c9c577f9c60896199/report.json`.

No product installer change was needed. This covers interruption during extraction into a new directory, not power loss, shortcut publication, automatic update activation or clean-machine acceptance. All fixture and failed-staging artifacts are retained on D:.

## Inventory hierarchy conflicts

The Python verifier and PowerShell installer reject inventories declaring both a file and its descendant, case-insensitively and in either order, before extraction. Shared parent directories remain valid. Real DSH development evidence: `.sumika-next/self-development-live-97a9611c68264659af039b89a8e4b1d8/reviewed-resume/report.json`; the host corrected a link-check ordering regression before adoption. 15 inventory/path tests and full installer fixtures passed.

One earlier regression run failed Directory.Move with access denied at publication; complete staged files remain at `.sumika-next/package/installer-check-c905b97c6ff445528f7c009256ee63b7`. A new isolated run passed (`installer-check-c4279ca5df584b9f9d52fcdc995cb812`). The cause is unproven, not fixed. Candidate f predates this change.

## Supplemental source notices for the next build

Four MIT notices are now included in `packaging/notices` for exact versions of pi-ai, pi-telemetry, xterm/headless and standardwebhooks. `sources.json` binds each to npm name/version/manifest SHA-256, fixed registry gitHead and notice hash. All eight missing-notice tarballs were downloaded and registry-integrity checked without installation; evidence is `.sumika-next/package/notice-source-fffb63d27d794440ba2c65e46bda5575`.

standardwebhooks uses Apache at repository root for the specification, but the SDK ancestor `libraries/LICENSE` is MIT; the pinned JavaScript package is 1.1.1. The SDK notice is shipped, not an inferred root license. The auditor recognizes exact supplemental bindings; changed versions or manifests receive no credit. 13 notice/inventory tests passed. Candidate f has not been rebuilt. AWS and koffi missing notices plus native-component terms remain unresolved; this is not complete redistribution clearance.

Koffi 3.2.1 parent tarball integrity and installed MIT notice bytes are verified; its exact optional dependency on `@koromix/koffi-win32-x64` 3.2.1 binds the fifth supplemental notice. AWS three packages remain unresolved (no gitHead, matching tags unavailable). `docs/project/native-component-review.json` joins Sharp native versions to its shipped README terms; this is a review inventory, not license/source compliance clearance. No package rebuild performed.

## Candidate g current-host acceptance

2026-09-19: product-candidate-20260919-g contains 26,048 verified files and current audio lifecycle, recovery preflight, header status and supplemental notices. Real ZIP/install/EXE startup, instance reuse, foreign-port refusal and owned shutdown passed: `.sumika-next/package/packaged-install-ae1e6e81487040fdad061f7f9b602448/report.json`. ZIP SHA256 `e939ace03e4251376f7fb5db3b6a84f5b061bbc0aff30b89cddc2787e3bb477a`.

Still INTERNAL: no clean-machine acceptance or daily replacement. License inventory `.sumika-next/package/license-audit-candidate-g.json` counts 500 npm and 2 Python packages; three AWS missing notices, sharp native terms and five embedded-text reviews remain. Earlier five supplemental notices are now included and matched. No public redistribution clearance.

## Complete-directory publication

The installer now requires a destination that does not exist, including refusing
an existing empty folder. It stages alongside the requested destination and
publishes with a single directory rename; it never moves release entries one by
one into a pre-existing directory. Choose a new versioned path without creating
the final folder beforehand. If another process creates that path during
extraction, publication fails and the staged package remains available for
inspection. Retry explicitly with another unused path; do not merge failed staging
into the old installation. No files or user data are deleted by this change.

Real PowerShell fixture evidence:
`.sumika-next/package/installer-check-9bc888f2b3a54807a32b6b35666b08a3/report.json`.
Existing-empty rejection, concurrent destination ownership, complete retained
staging, extraction interruption/retry and existing inventory checks passed.
The previous candidate-g archive/install result does not certify this newer
installer change. This is not power-loss durability, shortcut activation rollback,
automatic update or clean-machine acceptance.


## Embedded MIT text preservation

Five exact shipped README notice sections were reviewed and preserved under packaging/notices: data-uri-to-buffer 4.0.1, debug 2.6.9 and 4.4.3, jwa 2.0.1, jws 4.0.1. Source README SHA-256 and package manifest bindings are recorded in sources.json and docs/project/embedded-notice-review.json. debug 2.6.9 and jws 4.0.1 README copyright years are broader than standalone LICENSE; retain both. Thirteen notice/inventory tests passed. No package rebuilt, no upstream files modified, and the conservative audit gate remains open.


## AWS declared license terms

Official https://www.apache.org/licenses/LICENSE-2.0.txt is preserved for credential-provider-http 3.972.73, credential-provider-login 3.972.78 and nested-clients 3.997.45. Cached npm SHA512 integrity and archive manifest SHA256 match the shipped exact versions, which declare Apache-2.0. Binding/evidence: packaging/notices/sources.json and docs/project/aws-notice-review.json. These are generic declared license terms, not a verified version-specific source/NOTICE copy. The auditor now propagates supplemental unresolved obligations and keeps a release finding; 14 related tests passed. No package rebuilt and no redistribution clearance.


## Native component metadata coverage

The audit now compares the sharp README license table and versions.json in both directions using explicit component aliases. Candidate g declares libnsgif without a version; this was omitted by the earlier version-first review. Missing table/versions/declarations retain a native_component_metadata_incomplete finding. Its standalone LICENSE contains Apache terms only, while its package declaration also includes LGPL: full native terms and corresponding-source/build/relinking evidence remain pending. Seventeen tests passed; real 500 npm / 2 Python inventory retained the failing release gate. Evidence: .sumika-next/package/license-audit-candidate-g-components.json. No candidate rebuilt, binaries changed or release clearance granted.

## Clean Windows acceptance preparation

`python -B tools/prepare_clean_windows.py <archive> --sha256 <expected>` prepares
a Windows Sandbox `.wsb` file; it does not enable Windows features or start a VM.
Only its input bundle is mapped read-only, and its dedicated results folder is
writable. Networking, clipboard, audio/video input and printer redirection are
disabled. The guest uses the installed Python and existing inventory/EXE checks;
it does not depend on host Python, Node, credentials or a source checkout.

Candidate-h rehearsal passed on the current host; evidence is
`.sumika-next/package/clean-windows-candidate-h/host-results/report.json`.
The separate `results` folder is empty pending actual guest execution. A prepared
configuration or passing host rehearsal is not clean-machine acceptance. Feature
activation awaits user approval; the prepared command uses `-NoRestart`.
Final acceptance must use the final candidate, not this older candidate h.

## AWS source association completed

The fixed commit `cece9809ea2ed8fdb5f3e73972e2f71154b01129` contains the three exact
AWS package versions. Their source manifests match archived manifests after
expanding only the `workspace:` dependency prefix; their READMEs match byte for
byte. The full, untruncated source tree has no nearer license or applicable
NOTICE for these packages. `nested-clients` moved to `packages-internal` while
its published repository directory remained stale. Full source LICENSE text,
including Amazon copyright, is retained as `aws-sdk-js-v3-LICENSE.txt` and bound
to exact shipped manifests in `sources.json`. Details and limits are recorded
in `docs/project/aws-notice-review.json`; this is not a reproducible JavaScript
build claim or native dependency clearance. Nineteen notice/inventory/bundle
tests passed; these new notices still require a final package rebuild.


## Native source materials (partial)

Nine original source archives, including libvips 8.18.6 and eight LGPL/MPL dependencies, now match effective Windows recipe SHA256 values. All 28 declared component versions match after resolving build/overrides.mk and the mozjpeg plugin; the base MXE branch alone contains older defaults. Eleven exact source notice texts are retained in packaging/notices and bound to source archive hashes. Seventeen notice/inventory tests passed. See docs/project/native-component-review.json for evidence and remaining gaps. This does not establish original container identity, applied patches, complete transitive sources or relinking compliance. No public redistribution clearance or final candidate rebuild is claimed.


## Internal source-material bundle builder

`tools/build_native_source_materials.py --evidence <dir> --destination <bundle.zip>`
packages the verified cached source inputs and notices from
`packaging/notices/native-source-materials.json`,
`native-rust-source-materials.json` and `native-patch-materials.json` into an
internal source-material ZIP. It validates the three metadata ledgers before
copying any bytes — their list/object shapes, required safe names, lowercase
SHA-256 fields, and duplicate destination identities (case-insensitive) — and
rejects missing or linked source files. It refuses to overwrite an existing
destination archive or sidecar report, and never deletes partial output.

Success writes `materials-manifest.json` plus a sidecar report (`<bundle>.report.json`)
with `passed: true`. A caught failure after the output is claimed attempts to preserve a
sidecar report with `passed: false`, the exact failing stage, the reason, and the
entries already written, while the partial ZIP is retained for inspection. The
report status and `boundary` language assert source preservation only, never
public redistribution or release clearance.

```powershell
python -B -m unittest discover -s tests_next -p test_native_source_materials.py
```

Eighteen tests using retained fixtures cover success, invalid/duplicate/missing metadata,
early and later checksum failures with retained partial evidence, corrupt output
verification, existing ZIP/report refusal, competing writers, and Windows reserved names.
The report is exclusively created and updated through the same owned handle; report
I/O failures are attached to the original exception. A crash may leave an incomplete
report, which is not evidence of success. This is internal source-material
packaging, not complete corresponding-source or relinking delivery.

## Declared native source archive coverage

All 28 versioned native components now have original source archives whose SHA256 matches the effective Windows build recipe. The vendored libnsgif source is included in libvips. `packaging/notices/native-source-materials.json` records exact URLs/hashes and remaining obligations. Another 37 original notices and FreeType/IJG acknowledgments were preserved. The mozjpeg branch recipe uses the GitHub tarball API; a differently formatted codeload archive failed checksum and was not accepted.

This covers declared components, not the full transitive source closure (including Rust crates), applied patches or working relinking instructions. Cached archives do not constitute a delivered source bundle or public written offer. The native release gate remains open. Seventeen notice/inventory tests and the builder reviewed-asset hash gate passed.


## librsvg Rust source closure (partial build scope)

The Windows librsvg patch changes Cargo.lock. It was checked and applied with zero fuzz to the affected isolated files; it reduces registry packages from 350 to 346. All 346 effective-lock archives match locked SHA256 and embedded Cargo identities; original-lock evidence remains available. `tools/collect_locked_crate_sources.py <Cargo.lock> <cache>` reuses verified archives without executing package code and refuses corrupt cache/unsupported registries. It preserves failures rather than silently replacing them. The source identity list is shipped as `native-rust-source-materials.json`. This includes optional/build/test crates and is not a target-runtime SBOM. Missing standalone notices, target filtering, Rust build-std/toolchain source and full build/relinking still require review. Twenty-one tests and all builder notice hashes passed.


## Candidate Windows Rust dependency scope

Using existing Cargo 1.98.0, offline/locked metadata and tree resolution completed against isolated patched source and verified vendored crates. No build scripts ran and Cargo.lock stayed unchanged. The librsvg-c/capi normal+build graph for x86_64-pc-windows-gnullvm contains 162 entries. Under this candidate configuration, only mutants and selectors lacked standalone license files; the exact recorded-commit MIT text and official Mozilla MPL2 text were preserved respectively. Another 279 original/supplemental notice bindings cover the candidate graph. This is not proof of original feature detection, binary inclusion, historical toolchain provenance or native build/relink success. The full lock source cache remains retained. See docs/project/native-component-review.json.


## Candidate i current-host acceptance

The latest internal candidate contains 26,211 verified files, including bounded speech requests, consultation fixes and current supplemental notices. Archive SHA256: `d63324a24b94ab63ec4155438b5b8611bee4951b9c83739b80dfed672d60b96b`. Real archive/install/EXE lifecycle passed: `.sumika-next/package/packaged-install-40a3339d1e1b44ae99b6d025525803eb/report.json`. New clean-guest configuration: `.sumika-next/package/clean-windows-candidate-i/acceptance.wsb`; not executed. Strict audit still flags native obligations and five embedded README reviews, while exact AWS missing notices are resolved. No public clearance or daily replacement.


### Exact embedded MIT review recognition

The auditor recognizes `review_kind: verbatim_complete_mit_readme_v1` only when the
package ecosystem/name/version/manifest SHA-256, exact README path/hash, and
supplemental notice hash all match. The intact excerpt must occur in the README
(with only CRLF normalization); its complete standard MIT terms and copyright
lines must also be present. Keyword/length heuristics, partial excerpts, generic
licenses and unresolved review entries cannot clear a finding. Other findings,
including native/source obligations, remain independent. This is retained review
evidence, not automatic legal clearance. Exactly five previously reviewed records
currently carry this kind.

`python -B -m unittest tests_next.test_dependency_notices` covers the positive and
negative cases. Tests retain uniquely named fixtures under `.sumika-next/notice-tests`
instead of creating Python private-ACL temporary directories or deleting paths.
`python -B tools/verify_development_sandbox.py --notice-tests` runs the same reviewed
suite in the native Windows workspace-write sandbox without cloud calls; 14 tests
passed on 2026-09-19. This verifies compatibility, not ordinary model development.
Current candidate i remains unchanged; source metadata must be included in a future
verified package before its strict audit can reflect these reviewed findings.


### Candidate native patch verification

`tools/verify_native_source_patches.py` reuses the recorded component archives and
pinned Windows recipe archives; `packaging/notices/native-patch-materials.json`
records the candidate effective patch selection. The web static default variant
selects 16 patches across 28 components. All 16 passed dry-run and application with
`--fuzz=0` against fresh affected-file subsets; no upstream build scripts ran.
Explicit empty patch overrides remain empty rather than inheriting MXE defaults.
The default mozjpeg recipe archive is `mozjpeg.recipe-source`; the older retained
codeload archive is not hash-equivalent and must not be substituted.

This verifies a candidate build recipe, not the original container identity,
optional feature selection, compilation/relinking, or complete corresponding-source
delivery. Original archives and failed attempts remain retained. Do not clear the
native release gate on this evidence alone.


Patch verification now requires `--recipe-materials packaging/notices/native-patch-materials.json`.
Both exact recipe archive names and SHA-256 values must match before either archive
is parsed. Verified buffers are used directly. Every failure after output creation
retains a report with failure stage/reason and prior component results. Seven
small retained-fixture tests cover bad bindings, tampering, setup/source/patch
failure, and success; the 28-component / 16-patch real source check also passed.
This implementation was completed by the main Agent after the configured work
model failed to finish its separate isolated task; it is not evidence that the
work model autonomously completed development.


### Clean Windows long-path installation

The first candidate J Windows Sandbox run reached the real installer and failed
extracting a deep AWS SDK declaration file below the default WDAG user directory.
The host installation check had not exposed the clean Windows PowerShell 5.1
MAX_PATH behavior. The installer now enables modern .NET path handling for its own
process and uses extended-length paths for extraction and final directory rename;
it does not enable a machine-wide registry policy or shorten the selected install
location. Existing archive verification and no-overwrite publication remain in place.
The installer fixture includes an archive member exceeding MAX_PATH and checks its
exact bytes. The 2026-09-20 clean guest retest passed installation, all 26,214
inventory hashes, EXE first launch/reuse, foreign-port rejection/preservation and
authenticated shutdown with confirmed process exit. Evidence is under
`.sumika-next/package/clean-windows-candidate-j/results/retry-observed/`.
The original candidate J ZIP is unchanged; the corrected installer was supplied
separately. This is install/host lifecycle evidence, not all-feature acceptance.

The guest also exposed Python ordinary-path enumeration silently omitting 63 deep
files. `verify_portable_staging.py` now uses Windows extended paths and propagates
walk errors. Normal and extended-path comparisons proved the files already existed;
extended-path hash verification passed without enabling machine-wide long paths.
The PowerShell verifier redirects native stdout/stderr separately to preserve full
tracebacks instead of stopping on the first stderr line.


### Candidate toolchain source inventory

`packaging/notices/native-toolchain-source-materials.json` records the four
candidate MXE toolchain recipe archives, including Rust std/panic_abort inputs
and LLVM runtimes. The source-material builder reads it when present and requires
every declared archive at `<evidence>/toolchain/<component>-<version>.source`.
All hashes are checked from bytes actually written into the bundle. Missing or
mismatched files stop the build; adding a ledger is not proof its inputs exist.
The previous material bundles predate this ledger and do not contain these four
archives. Toolchain identity and actual build/relinking verification remain open.


Clean-guest verifier runs use a dedicated result directory. `progress.json` is
exclusively created before work starts and records PID, work directory, timestamp,
and input-validation/install/inventory/exe-lifecycle stage. A running record after
process loss is unknown, not success and not replay permission. Final report and
progress are retained; reusing an output directory is refused before creating a
new test installation. The current prepared candidate J retry predates these
checkpoints and must be inspected separately before scheduling any new run.


### Windows C++ wrapper rebuild evidence

The candidate J sharp addon loaded a locally rebuilt `libvips-cpp-8.18.6.dll`
from an isolated directory, using existing MSVC 14.44.35207 and checksum-verified
libvips sources/development headers. PNG pixel roundtrip, JPEG resize/encode/decode,
and SVG rasterization passed for original and replacement DLLs. Loaded-module
paths were checked in the Node diagnostic report. Reproduction commands, source
inputs, hashes and retained failures are in `cpp_rebuild_checkpoint` in
`docs/project/native-component-review.json`. The test uses process-local module
routing; no installed module or daily binary was changed. The C dependency DLL
was reused, so this is only C++ wrapper replacement evidence, not full MXE rebuild
or redistribution clearance.


The 2026-09-19 toolchain-inclusive internal source bundle now verifies 563 entries:
28 native sources, 346 Rust crates, 2 recipe archives, 4 candidate toolchain archives,
and notices/metadata. Rust 2026-06-05 and LLVM 22.1.7 source hashes match the pinned
recipes. Original LLVM runtime and Rust compiler-builtins/libm notices are preserved.
This completes collection of these four declared toolchain archives, not proof of
the historical build container, the target-specific standard-library link graph,
or all corresponding-source and relinking obligations. See the current
`toolchain_bundle_checkpoint` in the native component review for artifact/hash.
