# Third-party notices

Sumika does not copy CC Switch, Shinsekai, AIRI or N.E.K.O source code. Those
repositories are recorded as behavior and information-architecture references
in `docs/ui/license-ledger.md`; their code and assets are not redistributed by
this repository.

DeepSeek Harness is tracked as a separately managed MIT-licensed runtime at a
fixed commit in `docs/integrations/evolution-knowledge-registry.json`. Sumika
uses its public Web API through an adapter and does not redistribute or fork
the DSH Core. OpenAI Codex is an Apache-2.0 architecture reference only; no
Codex source is included. Tencent BrowserSkill is an MIT-licensed pinned backend
candidate; the first release includes only Sumika's policy companion and no
BrowserSkill extension, plugin, model or browser asset.

The CC Switch compatibility layer follows the MIT-licensed public import
protocol from the pinned `v3.20.0` commit. It is an independent parser with no
copied source. The notice is retained so a future copied implementation cannot
silently bypass attribution review.

Bundled or installed dependencies and the sample Avatar retain their own
license files and terms. See the license ledger and the package lockfile for
the exact versions and source records. Downloaded Ollama runtimes and model
weights are not redistributed by Sumika.

The default `assets/avatars/AvatarSample_A.vrm` and its thumbnail are VRoid
sample assets under the [VRoid Studio sample model conditions](https://vroid.pixiv.help/hc/en-us/articles/4402394424089),
not CC0. Copyright is not waived. They are provided as a free example Avatar,
not as an official Sumika character or a pixiv endorsement. Original source,
hashes, restrictions and the distribution allowlist are recorded in
`assets/avatars/README.md` and `assets/avatars/distribution.json`. Imported user
models are not part of the repository or application distribution.
