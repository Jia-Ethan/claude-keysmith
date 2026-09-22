# claude-keysmith GUI

## 桌面停更

這個獨立桌面不再發新的安裝包。已發出的版本保持原樣，不撤回，也不改成 Latest。之後的桌面只維護 [Keysmith Switch](https://github.com/Jia-Ethan/keysmith-switch)。範圍與進度見 [keysmith-switch#6](https://github.com/Jia-Ethan/keysmith-switch/issues/6)。

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
  tree (pipe drain after leader exit stays on the same deadline), sidecar-first
  CLI resolution (`CLAUDE_KEYSMITH_CLI` / `CLAUDE_KEYSMITH_PYTHON` env
  overrides). Packaged sidecar is CLI `v7.2`; GUI version comes from
  `package.json` (`0.1.0-beta.3`).
- `src/lib/parser.js` — `claude-keysmith/v1` JSON contract → view models.
- `src/lib/api.js` — invoke wrapper + preview/execute pairs (every call passes
  `--json`; execute appends `--yes`).
- `src/lib/store.js` + `windowLifecycle.js` — operation leases, exclusive write
  mutex, exit barrier with queued close (no tray).
