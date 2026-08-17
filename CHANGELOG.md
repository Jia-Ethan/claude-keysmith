# Changelog

## v7 / Desktop 0.1.0-beta.1 (Pre-release)

发布计划：本节内容将以同批次双 Pre-release 发布——`v7`（CLI）与 `desktop-v0.1.0-beta.1`（GUI beta），指向同一最终 main commit；草稿见 [`docs/release-notes-drafts.md`](docs/release-notes-drafts.md)，发布前置门槛见 [`docs/beta-acceptance.md`](docs/beta-acceptance.md)。

### Docs

- Rewrote the newcomer `README.md` / `README.en.md`: source CLI as the conservative path, unsigned Desktop Beta alongside it, one WARNING, and series links that drop `role-keysmith` and stop calling grok-keysmith an `AGENTS.md` installer.

### JSON 契约、事务恢复层与桌面客户端 (beta)

**`claude-keysmith/v1` JSON 契约：**

- `install` / `status` / `doctor` / `uninstall` / `restore` 支持 `--json` 稳定输出；写操作区分 `preview`（默认）与 `execute`（`--yes`）两种 mode，统一携带 `actions` / `warnings` / `blockers` / `backups` 证据列表。`blockers` 非空或 `ok:false` 即失败关闭。
- 新增只读命令 `backups --scope … --json`：只枚举通过命名规则校验的 keysmith 受控备份（`<target>.bak_YYYYMMDD_HHMMSS…`），并返回绝对 `target_path` 供受控恢复选择。
- 新增命令 `recover --scope …`：预览中断事务的残留与修复计划，`--yes` 执行恢复，重复执行幂等。
- `status --json` 在保留全部历史扁平键的同时新增结构化块：`presence`、`alignment`、`source_identity`、`runtime_readiness`、`recovery_state`。
- `restore` 新增可选 `--scope` / `--project-dir` 与 `--json`；带 scope 时只接受该 scope 的 `backups --json` 枚举出的 target / backup 精确配对，恢复走 journal/lock 事务并先生成 `*_pre_restore` 安全备份；无 scope 才保留 CLI 高级非受控恢复。
- `doctor --json` 键集合固定为 9 个不变，永不输出 Base URL / token / cookie / 非目标 settings 字段。契约参考见 `docs/json-contract.md`。

**Durable journal + write lock：**

- 所有写路径（install / uninstall / 受控 restore）由 scope 本地的排他锁（`.keysmith.lock`，O_EXCL，含 `{pid,label,acquired_at}`）与持久化事务日志（`.journal-<uuid>.json`，`claude-keysmith-journal/v1`）保护；每个 mutation 前后原子落盘 before/after 指纹。
- 两阶段 `pending` → `committed`：commit 前中断逆序回滚到之前的状态（恢复指纹校验过的备份，或删除事务新建文件）；commit 后永不反转，只做残留核验，核验干净的 journal 被下一次写入或 `recover` 消费。
- 修复 mutation 后指纹只更新了临时字典、没有写回实际 journal 的事务证据缺口；强杀后 recovery 现在能依据持久化 after 指纹精确判断，第三方后续修改仍会失败关闭。
- Windows 旧 launcher 迁移在任何移动前持久化 source / backup 路径与源指纹，并在每个成功移动后落盘进度；强杀发生在首个 rename 后也能由 `recover` 精确还原。恢复使用 no-overwrite 移动，悬空同名链接、被重建目标、篡改备份或同内容但不同文件身份的竞态均失败关闭并保留证据。
- 原子写临时文件采用 keysmith 专属命名；强杀遗留会让 status 标记 recovery-required、阻塞新写入，并由 recover 只读预览后定向清理。
- 失败关闭：活跃他方锁、损坏 journal、原子临时残留、未知修改（指纹既不等于 before 也不等于 after）、回滚目标被重建、找不到匹配备份等情况一律阻塞并保留证据。设计见 `docs/transaction-recovery.md`。

**unix wrapper 动态重解析（VERSION v6 → v7）：**

- 修复 macOS / Linux wrapper 将 `command -v claude` 的符号链接解析结果（版本目录）烙进 wrapper，导致 Claude 更新切换版本后失效的问题。
- wrapper 保留已解析路径作为快路径；路径消失时每次调用重新经 `command -v claude` 解析（zsh 下以 `disable -f claude` / `enable -f claude` 包裹，附 `command -v -p` 兜底）；全部解析失败返回 127 并给出干净诊断。
- `status` / `doctor` 对已消失的旧快路径按动态 wrapper 语义判断，不再在隔离 npm prefix 的 Claude Code 包版本目录切换成功后误报 `shell_wrapper_current:false` / `runtime_ready:false`；仍会拒绝任何其它 wrapper 结构漂移。

**参数校验：**

- `--max-tokens` 经 argparse `type=positive_int` 校验为正整数；0 / 负数 / 非数字给出干净的 usage error。runtime 仍为 user scope 专属。

**桌面客户端 `gui/`（`0.1.0-beta.1`，channel `beta`，未签名 Pre-release）：**

- Tauri 2 + React 19 + Vite + Tailwind 4 + Radix + Motion；PyInstaller onefile sidecar（`claude-keysmith-cli`）与 CLI 同源构建；react-i18next（zh-CN/en）。
- 页面：Dashboard / 三步 Deploy 向导 / Manage（uninstall、受控备份 restore、recover、repair）/ Settings。
- 进程边界：argv 数组调用（无 shell 拼接）、stdout/stderr 各 2 MiB 上限（截断失败关闭）、超时杀整棵进程树（unix 进程组 `kill(-pid)`；windows `taskkill /T /F`）、`kill_on_drop`。
- 单实例、全局写互斥（操作租约；`execute*` 写路径经 `cliRunExclusive` 持有独占租约）、关闭屏障（queued close，无托盘）；恢复只用 `backups --json` 的受控备份。
- 平台：macOS Apple Silicon `.app` + 未签名 `.dmg` 与 Windows x64 currentUser NSIS + WebView2 bootstrapper 均已通过原生候选构建和实体机用户路径验收，包括可见 UI、操作中关闭、旧 launcher、事务强杀恢复、无 WebView2、Gatekeeper 与 SmartScreen；无 Linux GUI、无自动更新、无签名/公证/Authenticode。见 `docs/desktop-gui.md`、`gui/SPEC.md`、`docs/platform-support.md`、`docs/beta-acceptance.md`。

### 发布候选构建链

- `gui-release-candidate` workflow 仅用 `contents: read` 且无 secrets：main PR 自动生成 `release_eligible:false` 的验证 artifact；合并后必须在 main 上传入精确 `expected_sha` 才能生成 `release_eligible:true` 候选。Windows x64 与 macOS ARM64 先跑 CLI / 前端 / Rust 全部门禁，再原生构建 PyInstaller sidecar 与 NSIS / DMG，核验安装/卸载或挂载、版本、架构、签名状态、source commit 与哈希后上传 artifact；不打 tag、不建 Release。
- Windows 候选在原生 runner 完成静默 currentUser 安装/卸载、冻结 sidecar runtime、PowerShell 5.1 / 7 wrapper、scoped restore、原子残留 recover、隐私、GUI 进程与单实例 smoke；另以 source-CLI pytest 覆盖旧 launcher 迁移/冲突与首个 rename 后强杀恢复，`BUILD_INFO.json` 明确标为 source-CLI 证据。安装器、GUI、sidecar 与 uninstaller 均确认 `NotSigned`。`SHA256SUMS` 强制写为 LF-only，并在上传前拒绝 CR 字节，保证 macOS/Linux 可直接 `shasum -c`。
- `docs/beta-acceptance.md` 记录 135 / 113 / 7 本地门禁、完整 ad-hoc 签名与 `spctl` 拒绝、真实进程组与 source-CLI 旧 launcher 首次移动后强杀的 recovery-required / 阻塞写入 / 纯只读预览 / 精确回滚链、隔离 npm prefix 与用户安装路径的 Claude 版本切换，以及 macOS / Windows 全部实体机用户路径验收；维护者于 2026-08-15 确认第二节实体机项目全部通过。
- 发布政策明确区分：无签名 / notarization / Authenticode / 自动更新是 `desktop-v0.1.0-beta.1` 已接受且必须披露的限制；实体机门禁已完成，外发前只需精确 main SHA 的 `release_eligible:true` 候选、完整校验信息与明确发布授权。
- `docs/reference.md` 修正残留的 “v6 当前模板” 为 v7；新增 `docs/release-notes-drafts.md`（v7 与 desktop-v0.1.0-beta.1 同批次双 Pre-release 草稿，未写发布日期）。

### Review 修复（本轮）

- **构建门禁解耦**：`externalBin` 从常驻平台配置移到打包专用的 `gui/src-tauri/tauri.bundle.conf.json`（由 `npm run bundle` 的 `tauri build --config` 引入）。干净检出上 `cargo fmt --check` / `cargo check --locked` / `cargo test --locked` 不再因缺少（且被 gitignore 的）sidecar 产物而失败。
- **`recover` 预览与执行同源判定**：新增只读检查函数 `plan_pending_rollback`（读取指纹与备份证据，但不写入、删除或重命名），预览阶段就展开具体修复步骤并对不可恢复情形（未知修改、找不到匹配指纹的备份、回滚目标被重建）返回 blocker，消除“预览 `ok:true` → 确认 → execute 才失败”的 GUI 确认缺口。
- **全局写互斥真正接线**：`beginExclusiveOperation` 原本无生产调用方；新增 `cliRunExclusive`，`executeInstall` / `executeUninstall` / `executeRestore` / `executeRecover` 均改走独占租约，preview 与读操作保留共享租约。
- **`--json` 下的参数校验错误输出契约 JSON**：argparse usage error（如 `--max-tokens 0`）现在向 stdout 输出 `ok:false` / `exit_status:2` 的契约文档，usage 文本仍在 stderr；GUI 不再报“CLI 未输出稳定 JSON”而是显示真实原因。
- 移除无调用方的 `_rollback_moved_pairs`；`cli_runner.rs` 的 stdout/stderr 管道缺失从 `expect` panic 改为终止子进程并失败关闭；vite `manualChunks` 拆分 react / radix / motion / i18n，消除 >500 kB chunk 警告（当前最大 chunk 200.09 kB）。
- 文档同步：`gui/SPEC.md`、`docs/desktop-gui.md` 的写互斥表述改为与实现一致；`docs/transaction-recovery.md` 补充预览/执行同源判定与非受控 `restore` 的事务边界；`docs/json-contract.md` 记录 usage error 的 JSON 行为。

### Windows wrapper retry safety

- PowerShell wrapper 只在调用运算符无法解析尚未启动的候选入口时继续选择其他候选。
- 已启动 `.ps1` 脚本内部抛出的 `CommandNotFoundException` 或 `ItemNotFoundException` 会立即返回给调用方，不再进入等待循环或重复执行命令。

## v6 (2026-08-07)

### Windows updater resilience

修复 Windows runtime wrapper 将 npm 的 `claude.ps1` shim 固化为唯一入口后，Claude Code 更新期间或安装方式变化时出现 `required file is missing` 的问题。

**上游入口解析：**

- PowerShell wrapper 不再依赖安装时捕获的单一 npm shim，而是在每次调用时动态选择可用的 Claude Code 入口。
- Windows 候选顺序为：strict `CLAUDE_KEYSMITH_CLAUDE_BIN` 覆盖、`~/.local/bin/claude.exe`、PATH 中非 npm prefix 的 WinGet/native `.exe`、npm 包内 `bin/claude.exe`、npm `claude.cmd` / `claude.ps1` / `claude.exe` shim 兜底。
- 候选解析会排除 claude-keysmith 自己管理或遗留的包装器，避免递归调用。
- 所有候选暂时缺失时，每 250 ms 重新检测一次，最多等待 10 秒；上游进程一旦启动，不因非零退出或中断而自动重试，避免重复执行命令。
- wrapper 继续注入 system/append 两个 prompt 文件、完整透传参数并保留上游退出码；失败使用 terminating error，不关闭当前 PowerShell 会话。

**Windows 升级与兼容：**

- `install --scope user --runtime` 会在写入前检查 `~/.local/bin/claude.ps1` 和 `claude.cmd`。
- 只有确认属于旧 keysmith/prompt wrapper 的 `.ps1`，以及仅转发到同目录 `.ps1` 的 `.cmd`，才会在 `--yes` 下重命名为唯一 timestamp 备份。
- 无法确认所有权的同名 launcher 会在 dry-run 和写入模式中报告冲突；工具不会修改它，也不会执行其他 runtime 写入。
- PowerShell profile 从实际用户级 `PSModulePath` 的首个可识别条目派生，支持重定向后的 Documents 目录和尚未创建的已声明用户 `Modules` 目录；无法识别时要求显式设置 `CLAUDE_KEYSMITH_SHELL_RC`。
- 正式支持范围为 Windows PowerShell 5.1 与 PowerShell 7；CMD 和 Git Bash 不属于 v6 managed wrapper 支持范围。

**状态、诊断与文件安全：**

- 新增 `--version`，输出 `claude-keysmith v6`。
- runtime status 新增 `upstream_candidates`、`upstream_path`、`upstream_exists`、`shell_wrapper_current`、`legacy_launcher_detected`、`legacy_launcher_paths`、`legacy_launcher_conflict`、`legacy_launcher_conflict_paths`、`upgrade_required`，同时保留已有字段。
- `runtime_ready` 现在要求 prompt 文件完整、settings 对齐、wrapper 为 v6 当前模板、至少一个上游入口存在，并且没有未迁移或冲突的旧 launcher。
- `doctor` 不再输出 Base URL 或潜在凭证，只报告安装类型、路径、候选拒绝原因与修复动作。
- 同一秒内的备份使用唯一文件名，不覆盖既有恢复点；原子写入失败时清理临时文件。

**升级：**

```powershell
python .\claude-instruct.py install --scope user --runtime       # 先预览迁移与写入
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
python .\claude-instruct.py doctor --json
```

安装 Agent 不得自行创建或替换 `~/.local/bin/claude.ps1`、`~/.local/bin/claude.cmd`；Claude Code 二进制及其 launcher 由上游安装器管理。

**验证与发布边界：**

- 本地 `py_compile`、Python 3.9/3.14 全量 pytest 与文档一致性检查通过。
- GitHub Actions 的 Ubuntu、macOS、Windows × Python 3.8/3.14 矩阵，以及 Windows PowerShell 5.1 / PowerShell 7 wrapper 实际加载与执行均通过。
- 用户安装路径的真实 Claude Code 升级已完成验收；人工真实 Ctrl+C 仍保留为独立补验边界，子进程返回 130 不等同于真实 Ctrl+C。
- 已发布的 `v6` tag 对 `.ps1` 上游内部抛出的两类路径异常存在误重试风险；修复已纳入 `v7` Pre-release。

## v5 (2026-07-29)

### Windows / PowerShell 运行时支持

添加完整的 Windows 环境下 `--runtime` 支持，以及跨平台的 shell 自动检测。

**新增函数：**

| 函数 | 用途 |
|---|---|
| `resolve_home()` | `$CLAUDE_KEYSMITH_HOME` → `$HOME` → `Path.home()` 三级优先解析；修复 Windows 上 `Path.home()` 忽略 `$HOME` 的问题 |
| `runtime_shell_kind()` | `os.name == "nt"` 返回 `"powershell"`，否则 `"zsh"`；可通过 `$CLAUDE_KEYSMITH_SHELL` 覆盖 |
| `powershell_profile_path()` | 根据 `PSModulePath` 区分 PS5（`WindowsPowerShell`）vs PS7（`PowerShell`）的 profile 路径；可通过 `$CLAUDE_KEYSMITH_SHELL_RC` 覆盖 |
| `find_claude_binary()` | 依次查找 `claude.cmd` / `claude.exe` / `claude`，fallback 到 `%APPDATA%/npm/claude.cmd`；可通过 `$CLAUDE_KEYSMITH_CLAUDE_BIN` 覆盖 |
| `_powershell_quote()` | PowerShell 单引号转义，`' → ''` |

**修改函数：**

- `render_shell_wrapper()` — 新增 `shell_kind` 参数；`shell_kind == "powershell"` 时生成 `function global:claude { … @args }`，否则生成 `claude() { … "$@" }`
- `user_runtime_paths()` — 返回类型 `Dict[str, Path]` → `Dict[str, Any]`；新增 `shell_kind` 和 `shell_rc` 字段；`"zshrc"` 键保留为 `shell_rc` 的别名
- `resolve_scope()` — user scope 使用 `resolve_home()` 替代 `Path.home()`
- 所有 install / uninstall / status / doctor 命令 — 固定 `zshrc` 引用改为 `shell_rc`，并输出 `shell_kind`；reload 提示根据平台给出 `source ~/.zshrc` 或 `. $PROFILE`

**新增环境变量：**

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CLAUDE_KEYSMITH_HOME` | `$HOME` → `Path.home()` | 覆盖 home 目录解析 |
| `CLAUDE_KEYSMITH_SHELL` | `nt` → `powershell`，否则 `zsh` | 强制 shell 类型 |
| `CLAUDE_KEYSMITH_SHELL_RC` | 自动推断 | 强制 shell profile 路径 |
| `CLAUDE_KEYSMITH_CLAUDE_BIN` | 自动检测 | 强制 claude 二进制路径 |

**向后兼容：**

- macOS / Linux 行为完全不变
- 所有 `CLAUDE_KEYSMITH_*` 环境变量可选，自动检测开箱即用

**Windows 安装示例：**

```powershell
python .\claude-instruct.py install --scope user --runtime       # 预览
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py doctor --json
```

**文档更新：**

- README.md / README.en.md — 新增 Windows PowerShell 快速开始节、环境变量说明、兼容性更新
- docs/reference.md — 新增 runtime 层 Windows profile 说明、环境变量覆盖参考表
- docs/agent-install.md — 新增 Windows PowerShell 安装流程

**测试：**

- 新增 6 个测试覆盖 Windows 路径解析、shell 检测、二进制查找、PowerShell wrapper 生成、runtime install/uninstall 端到端流程
- 全量 28 个测试通过
