# claude-keysmith GUI

Desktop client for `claude-keysmith` (`../claude-instruct.py`): a visual wrapper
for Claude Code instruction + runtime injection. Tauri 2 + React + Vite.

## Develop

```bash
npm install
npm test            # vitest (parser/store/windowLifecycle/view logic)
npm run dev         # vite dev server (Tauri: npm run tauri dev)
```

## Build gates

```bash
npm run build                          # vite production build
npm run build:sidecar                  # PyInstaller onefile CLI sidecar (native only)
npm run bundle                         # canonical distributable build (sidecar first)
cd src-tauri && cargo fmt --check && cargo check --locked && cargo test --locked
```

- `scripts/generate-build-info.mjs` runs before dev/build/test and writes
  `src/lib/build-info.generated.js` (GUI version from package.json, channel
  `beta`, source commit from `git rev-parse HEAD`; no hardcoded release claims).
- `scripts/build-sidecar.mjs` bundles `../claude-instruct.py` plus `../examples/`
  (frozen resources resolve via `sys._MEIPASS`, see `_resource_base()` in the
  CLI). Set `PYTHON` to an environment with `pip install -r requirements-build.txt`.
- `npm run bundle` is the only supported distributable-build entry point. The
  base config keeps direct `tauri build` executable-only, and its bundle hook
  rejects an explicit `--bundles` override; the packaging overlay enables
  bundles only after the target sidecar exists. Packaging is handled outside
  this worktree.

## Architecture

- `src-tauri/src/cli_runner.rs` — process boundary: argv-array invocation,
  2 MiB output cap (fail closed on truncation), timeout kills the full process
  tree, sidecar-first CLI resolution (`CLAUDE_KEYSMITH_CLI` /
  `CLAUDE_KEYSMITH_PYTHON` env overrides).
- `src/lib/parser.js` — `claude-keysmith/v1` JSON contract → view models.
- `src/lib/api.js` — invoke wrapper + preview/execute pairs (every call passes
  `--json`; execute appends `--yes`).
- `src/lib/store.js` + `windowLifecycle.js` — operation leases, exclusive write
  mutex, exit barrier with queued close (no tray).
