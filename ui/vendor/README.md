# Vendored UI renderer

`sumika-vrm-viewer.js` bundles three.js (MIT) and @pixiv/three-vrm (MIT) into a
single ES module that exports `mountVrmViewer(container, url, options)`. It was
authored for Sumika and copied byte-identically from the UI design project
(`D:\Code\Sumika-UI-Designs\direction-d-hiyori\vendor\sumika-vrm-viewer.js`).

- SHA-256: `b3fa67be87edd1cf1da594519da0b45ae35ee01f7ad07a...` (verify with `Get-FileHash`)
- It renders only local files served by `ui/server.py`; it never uploads a model.

The demo model `extensions/roles/defaults/sampleA/AvatarSample_A.vrm` is a VRoid
Studio sample distributed via `madjin/vrm-samples`. It is **not** CC0: use as an
app avatar and in images/videos is allowed under the sample terms, relicensing
as CC0 and selling the unmodified sample are not. See the license ledger kept in
the UI design project's `assets/README.md` before redistributing the asset.
