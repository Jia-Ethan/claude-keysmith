<!-- markdownlint-disable MD013 -->
# Beta 验收清单（`0.1.0-beta.1`）

本文区分"已实际取得证据"与"发布前必须在实体机/原生 runner 验证"两类。**本分支不发布任何产物**；GUI 是未签名的 beta，外发前必须完成第二节全部 PENDING 条目。

验证环境（发布候选轮，分支 `prep/gui-release-candidate`，base `bbd8ca15`）：macOS 26.5.2 / Apple Silicon（arm64）实体机；Python 3.14.6 独立 venv（`gui/requirements-build.txt` + pytest）；Node 25.9.0 / npm 11.12.1（`npm ci`）；rustc 1.93.1。所有 CLI 验证在隔离 `HOME` / `CLAUDE_KEYSMITH_HOME` / `CLAUDE_KEYSMITH_SHELL_RC` 与 fake Claude 上游下进行，未触碰真实 `~/.claude` 或真实 shell profile。

## 一、发布候选轮已取得证据的验证

### 门禁（本机，隔离环境）

| 项目 | 命令 / 方式 | 结果 |
|---|---|---|
| CLI 语法 | `python3 -m py_compile claude-instruct.py` | 通过 |
| CLI 测试套件 | 隔离 `HOME` / `CLAUDE_KEYSMITH_HOME` 下 `python3 -m pytest -q tests` | **121 passed** |
| 前端测试 | `cd gui && npm test`（vitest） | **11 文件 113 passed** |
| Rust 门禁 | `cargo fmt --check && cargo check --locked && cargo test --locked` | **7 passed**（干净检出，无需 sidecar） |
| 前端生产构建 | `npm run build` | 通过，最大 chunk 200.09 kB，无 >500 kB 警告 |
| sidecar 构建 | `npm run bundle` 内含 `build:sidecar`（PyInstaller onefile + `--version` smoke） | 通过（`aarch64-apple-darwin`，报 `claude-keysmith v7`） |
| macOS 发行打包 | `npm run bundle` → `.app` + `.dmg`；`hdiutil verify` | 通过（DMG checksum VALID） |
| DMG 挂载检查 | `hdiutil attach` 后 `file` + 执行内嵌 sidecar | 内嵌 sidecar 为 Mach-O arm64，`--version` 报 `claude-keysmith v7` |
| git 卫生 | `git diff --check` | 干净 |

### 未签名状态记录（macOS，真实结果，不伪装）

- `codesign -dv <app>`：`Signature=adhoc`，flags `0x20002 (adhoc,linker-signed)`——仅 linker 自动 ad-hoc 签名，无开发者身份。
- `spctl --assess --type execute <app>`：**拒绝**（exit 1，`code has no resources but signature indicates they must be present`）。Gatekeeper 不放行是未签名 beta 的预期现状；发布说明必须包含手动放行指引，用户侧提示文案见下方 PENDING 条目。

### 失败关闭专项（macOS 实体机实测）

| 项目 | 证据 | 结果 |
|---|---|---|
| 超时杀整棵进程树 | `cargo test timeout_terminates_descendant_processes`：真实 `/bin/sh` 派生 `sleep 60` 后代，100ms 超时后验证后代 PID 被杀 | 通过 |
| 2 MiB 输出失败关闭 | `cargo test oversized_output_fails_closed`：真实 `dd` 输出 3 MiB，`cli_run` 返回明确错误（"CLI 输出不完整，已阻止继续操作"），不解析半截输出；前端 parser 对未闭合 JSON 返回"输出不完整"（vitest 覆盖） | 通过 |
| 写入中强杀 → recovery-required | 对真实 sidecar `uninstall --runtime --yes` 在 journal 出现实际 step 时 `SIGKILL` 整个进程组；重启后 `status --json` 报 `recovery_required: true`、`must_recover_before_writes: true` | 通过 |
| pending journal 阻塞后续写入 | 上述状态下 `install --yes` 返回 `ok:false` + blocker（"检测到未完成的事务…请先运行 recover"） | 通过 |
| recover 预览纯只读 | recover 预览前后对整个隔离 HOME 做 `stat`（mtime+size）全树快照 diff：零差异；预览列出 `rollback-pending` 计划 | 通过 |
| recover 执行回滚 | `recover --yes` 后 journal 被消费、锁被回收（actions：`reclaim-lock`、`cleanup-journal`），被中断 uninstall 撤销、import block 还原 | 通过 |
| committed journal 不反撤 | 构造 commit 后崩溃残留的 committed journal；下一次写入消费该 journal，目标文件 SHA-256 前后不变 | 通过 |
| 活锁拒绝 | 存活进程持有 `.keysmith.lock` 时写入 `ok:false`（"另一个 keysmith 写入正在进行"）；死 PID stale lock 被回收后写入正常 | 通过 |
| 全局写租约边界 | vitest：execute 走独占租约、并发写拒绝、preview/读操作走共享租约不被误锁、后端同步抛错时租约释放（`api.test.js` / `store.test.js`，113 passed 内） | 通过 |

### GUI 运行时（macOS 实体机，release `.app`，隔离环境）

| 项目 | 证据 | 结果 |
|---|---|---|
| sidecar 探测（bundled） | 隔离 env 启动 release `.app`：`ps` 观察到 `.app` 内部 `claude-keysmith-cli --version` 探测子进程执行并退出；sidecar 报 `claude-keysmith v7` | 通过（进程级证据；UI 展示值人工复核见 PENDING） |
| 关闭窗口无孤儿进程 | 点击窗口关闭按钮后 GUI 进程退出，`pgrep` 确认无残留 `claude-keysmith-cli` 进程 | 通过（空闲关闭；操作中排队关闭的 UI 端到端见 PENDING，逻辑由 store 单测覆盖） |
| Deploy 等价 CLI 链 | sidecar `install --scope user --runtime` preview（`ok:true`，7 actions，无写入）→ execute（`ok:true`）→ 新 zsh 会话 source 隔离 rc 后 `claude` wrapper 注入 `--system-prompt-file`（fake 上游 arg log 验证） | 通过（CLI 层；GUI 向导 UI 端到端见 PENDING） |
| Manage 等价 CLI 链 | `backups --json`（只读枚举受控备份）→ `restore --target --backup` preview（全树快照零差异）→ execute（生成 `pre_restore` 安全备份，目标等于备份内容）→ `uninstall --runtime` preview+execute（wrapper 从 rc 移除） | 通过（CLI 层；GUI 页面 UI 端到端见 PENDING） |
| doctor / backups 不泄漏 | `doctor --json` 键集合固定 9 键；断言输出不含 token / cookie / Bearer / sk- / base_url / ANTHROPIC 字样；`backups --json` 仅含路径与元数据（`backup_path`/`sha256`/`size_bytes`/`created`/`kind`），无文件内容 | 通过 |

## 二、发布前必须补齐的验证（PENDING，未通过不得外发）

### macOS ARM64 实体机

- [ ] 从干净（或新建隔离）账户打开未签名 `.app` / `.dmg`，确认 Gatekeeper 提示文案可接受并写入发布说明（当前 `spctl` 拒绝状态见上文，需人工记录用户视角文案）。
- [ ] GUI Dashboard UI 中人工确认 runtime=`bundled` 与 CLI 版本 `v7` 的展示值。
- [ ] Deploy 向导 UI 端到端：三步向导完整执行 user runtime 安装（CLI 层已验证，需在 GUI 内走完确认交互）。
- [ ] Manage 页 UI 端到端：uninstall / restore / recover 的 preview → confirm → execute 报告展示正确。
- [ ] 操作进行中点击关闭窗口：退出排队、操作完成后窗口才销毁（空闲关闭与无孤儿已验证；排队路径逻辑有单测，需 UI 实测）。
- [ ] 真实 Claude Code 升级（版本目录切换）后 wrapper 仍可用（需真实 Claude 安装，隔离环境无法覆盖）。

### Windows x64 原生环境（全部 PENDING）

`.github/workflows/gui-release-candidate.yml`（手动触发，`permissions: contents: read`，只上传 artifact，不打 tag、不建 Release）在 windows-latest 上执行 CLI/前端/Rust 门禁 + 原生 PyInstaller sidecar + NSIS bundle，产出安装器、sidecar、`BUILD_INFO.json` 与 `SHA256SUMS`。该 workflow 尚未在远端执行过；以下条目待第一次成功运行与人工验收：

- [ ] workflow 首跑成功：原生 sidecar `--version` smoke + NSIS currentUser 安装器产出。
- [ ] 实体机安装 → 启动 → sidecar 探测 → Deploy（PowerShell profile wrapper，`. $PROFILE` 生效）。
- [ ] uninstall / restore / recover / 退出行为同 macOS 清单。
- [ ] 旧 launcher 迁移与同名冲突路径（`~/.local/bin/claude.ps1` / `claude.cmd`）。
- [ ] WebView2 bootstrapper 在无 WebView2 机器上静默安装。
- [ ] 未签名 SmartScreen 提示文案确认并写入发布说明。
- [ ] 失败关闭专项在 Windows 侧复验（超时杀树 `taskkill /T /F`、2 MiB 截断、中断恢复）。

## 三、发布边界声明

- 本分支仅产出源码、文档与候选构建链；发行打包只用 `npm run bundle`。
- 候选产物（DMG / NSIS / sidecar / `SHA256SUMS` / `BUILD_INFO.json`）只存在于本地候选目录与 CI artifact，不上传 Release。
- 无代码签名、无 notarization / Authenticode、无自动更新、无 Linux GUI——这些是发布前显式门槛（见 [`platform-support.md`](platform-support.md)）。
- 发布采用同批次双 Release：`v7`（正式，CLI）与 `desktop-v0.1.0-beta.1`（Pre-release，GUI beta），指向同一最终 main commit；第二节全部条目勾选并记录前，`0.1.0-beta.1` 不得对任何外部渠道发布。
