# Scene-first UI shell

The client is a single full-screen scene viewport, not a page-tab tool. The
character IS the interface: the viewport is always visible and everything else
floats above it. This contract was introduced in the 2026-09-04 UI reset and
replaces the former 11-item sidebar workspace.

## Three layers

1. **Scene viewport** (`z-0/1`): a backdrop layer (solid color now; local
   image; video/web wallpaper later; eventually a live 3D dwelling) plus the
   always-mounted Avatar stage. Opening a drawer dims and blurs the scene; the
   WebGL canvas is never unmounted across navigation.
2. **Heads-up layer** (`z-10/20`): a floating topbar (character pill, LLM /
   core / privacy pills, Avatar toggle, pet-mode button), the vertical dock
   (`z-40`, always above drawers), the chat column (bubble history + a
   visual-novel style dialogue-box input with the character nameplate), and a
   one-time welcome card.
3. **Drawer layer** (`z-30`): four fullscreen drawers take over when opened —
   工作台 (Agent sessions, web consultation, tasks, history, notifications),
   角色 (character editor + Avatar library), 模块 (module cards, the
   "＋ 添加模块" library, provider/web-chat config, developer tools), and
   设置 (appearance, data directory, snapshots). `Esc` or ✕ returns to the
   scene. The desktop pet overlay is the same shell with the viewport
   transparent and only the dialogue box mounted.

## Theme system

All visual properties derive from CSS variables in `styles.css`. The repo
default is deliberately project-neutral (night-blue surfaces, one mint accent);
no character-specific brand color may be committed. A character may carry
`config.theme.accent` (a hex color): `applyCharacterTheme()` sets `--accent`
and every derived tint is produced with `color-mix`, so selecting a character
reskins the whole shell. Character card imports pick up
`data.extensions.theme_color` / `accent_color` / `accent` automatically
(validated hex, else ignored); the character editor exposes an explicit
accent picker with a "restore default" escape hatch.

## Background slots

`.scene-backdrop` renders in order: local image (stored as a data URL in
`localStorage`, ≤4.5 MB, never uploaded) → solid swatch → the default night
gradient. Video and web-page dynamic wallpapers are later layers on the same
element; Wallpaper Engine native scene rendering is a research item (its
`.pak` runtime is proprietary; web-type WE wallpapers would go through the
web-wallpaper layer instead).

## Borrowed patterns

Layout layering, mutually-exclusive panels and the visual-novel textbox are
interaction patterns studied from MIT-licensed projects (Amica, ChatVRM,
Open-LLM-VTuber-Web); no upstream file is copied and every visible surface is
re-expressed with the Sumika token system. See `docs/ui/license-ledger.md`.

## Future mount points

- Voice / screen-watch / watch-together: HUD widgets on layer 2.
- Real-world devices (camera, RC car as her body): HUD device widget; the
  viewport can switch to a live camera source via the backdrop slot.
- Dwelling observation (she sleeps, works, eats on her own schedule):
  replace the backdrop+stage contents; the HUD and drawers are unchanged.
- Multiple characters sharing one house: more actors in the viewport and
  multiple nameplates in the dialogue layer; per-character `theme.accent`
  already exists.

## 相关文档

- [Character configuration](characters.md)
- [Modules](modules.md)
- [需求基线](../requirements/baseline.md)
