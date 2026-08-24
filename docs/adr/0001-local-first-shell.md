# ADR 0001: dependency-light first shell

## Decision

The first runnable vertical slice uses Python's standard library for the local
core and a browser shell that keeps its business logic dependency-light. The
shell may load explicitly pinned renderer bundles, currently the local VRM
adapter, while the intended production UI remains Vue/TypeScript inside a
Tauri desktop shell. `frontend/package.json` and `frontend/src/main.ts`
preserve that migration boundary.

## Why

At the beginning of the project the repository had no lockfile or installed
frontend/runtime dependencies. That historical constraint led to a browser
preview which made the protocol, page structure and user flow testable without
hiding behavior behind a generated scaffold. The current frontend now has its
own lockfile and pinned renderer dependencies; the original decision remains a
boundary decision, not a claim about the current repository state.

## Consequences

- Live2D remains a future renderer; VRM uses the pinned local Three.js adapter
  and keeps the same renderer-neutral core boundary.
- The static shell must not grow business logic; it is a client of `/rpc` and
  `/ws/events`.
- Installing Vue/Vite/Tauri later should replace the renderer, not the routes,
  events, provider contracts or storage schema.

## 相关文档

- [架构索引](../architecture/README.md)
- [Desktop shell](../architecture/desktop-shell.md)
- [状态矩阵](../status-matrix.md)
