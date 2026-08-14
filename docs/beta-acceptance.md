<!-- markdownlint-disable MD013 -->
# Beta 验收清单（`0.1.0-beta.1`）

本文区分"已实际取得证据"、"发布前必须补齐的验证"与"本次未签名 beta 已接受的限制"。**本分支不发布任何产物**；外发 `desktop-v0.1.0-beta.1` 前必须完成第二节全部未完成条目。代码签名、公证、Authenticode 与自动更新不属于这次明确标记为未签名 beta 的阻塞项，但必须在产物与发布说明中如实披露。

验证环境（发布阻塞修复轮，分支 `fix/desktop-gui-p0-recovery`，base `f8b8234f`）：macOS 26.5.2 / Apple Silicon（arm64）实体机；Python 3.14.6 独立 venv（pytest 9.1.1）；Node 25.9.0 / npm 11.12.1（`npm ci`）；rustc 1.93.1。所有 CLI 验证在隔离 `HOME` / `CLAUDE_KEYSMITH_HOME` / `CLAUDE_KEYSMITH_SHELL_RC` 下进行，未触碰真实 `~/.claude` 或真实 shell profile；真实 Claude 版本切换专项仅运行临时 npm prefix 中的 `claude --version`。

## 一、发布候选轮已取得证据的验证

### 门禁（本机，隔离环境）

| 项目 | 命令 / 方式 | 结果 |
|---|---|---|
| CLI 语法 | `python3 -m py_compile claude-instruct.py` | 通过 |
| CLI 测试套件 | 隔离 `HOME` / `CLAUDE_KEYSMITH_HOME` 下 `python3 -m pytest -q tests` | **135 passed** |
| 前端测试 | `cd gui && npm test`（vitest） | **11 文件 113 passed** |
| Rust 门禁 | `cargo fmt --check && cargo check --locked && cargo test --locked` | **7 passed**（干净检出，无需 sidecar） |
| 前端生产构建 | `npm run build` | 通过，最大 chunk 200.18 kB，无 >500 kB 警告 |
| sidecar 构建 | `npm run bundle` 内含 `build:sidecar`（PyInstaller onefile + `--version` smoke） | 通过（`aarch64-apple-darwin`，报 `claude-keysmith v7`） |
| macOS 发行打包 | `npm run bundle` → `.app` + `.dmg`；`hdiutil verify` | 通过（DMG checksum VALID） |
| DMG 挂载检查 | `hdiutil attach` 后 `file` + 执行内嵌 sidecar | 内嵌 sidecar 为 Mach-O arm64，`--version` 报 `claude-keysmith v7` |
| git 卫生 | `git diff --check` | 干净 |

### PR 验证候选（GitHub Actions 原生 runner）

| 项目 | 方式 | 结果 |
|---|---|---|
| provenance | main PR 自动构建 | `artifact_class=pr-validation`、`release_eligible=false`；PR artifact 的 `source_commit` 是 GitHub merge SHA，`pr_head_commit` 才是被验证的分支 SHA |
| macOS ARM64 | Python / 前端 / Rust 门禁 → 原生 PyInstaller sidecar → DMG → 挂载、架构、版本、ad-hoc 签名、最低系统与 Gatekeeper assessment | 通过（125 / 113 / 7）；下载后的 `BUILD_INFO.json`、`SHA256SUMS` 与两个产物独立复核一致 |
| Windows x64 | Python / 前端 / Rust 门禁 → 原生 PyInstaller sidecar → NSIS currentUser 安装器 → 静默安装/卸载及冻结 sidecar smoke | 通过（123 passed + 5 skipped / 113 / 7）；安装器、GUI、sidecar、uninstaller 均为 `NotSigned` |
| Windows 已安装链路 | runtime install/uninstall、PowerShell 5.1 / 7 wrapper、scoped restore、原子残留 recover、doctor/backups 隐私、GUI 进程与单实例 | 通过；均使用 runner 临时隔离 HOME/profile/fake upstream |
| 校验清单可移植性 | 两端 artifact 下载后以 macOS `shasum -a 256 -c SHA256SUMS` 独立校验；Windows workflow 拒绝 `SHA256SUMS` 中的 CR 字节 | 通过后方可作为候选证据；首轮发现并修复了末行 CRLF 会破坏 Unix 校验的问题 |

### 未签名状态记录（macOS，真实结果，不伪装）

- `codesign -dvvv <app>`：`Signature=adhoc`，flags `0x2 (adhoc)`，`TeamIdentifier=not set`；整包 `codesign --verify --deep --strict` 通过，但没有 Developer ID 身份、notarization 或 hardened runtime。
- `spctl --assess --type execute <app>`：**拒绝**（exit 3，`rejected`）。Gatekeeper 不放行是未签名 beta 的预期现状；发布说明必须包含手动放行指引，用户侧提示文案见下方 PENDING 条目。

### 失败关闭专项（可复现自动化与隔离命令证据）

| 项目 | 证据 | 结果 |
|---|---|---|
| 超时杀整棵进程树 | `cargo test timeout_terminates_descendant_processes`：真实 `/bin/sh` 派生 `sleep 60` 后代，100ms 超时后验证后代 PID 被杀 | 通过 |
| 2 MiB 输出失败关闭 | `cargo test oversized_output_fails_closed`：真实 `dd` 输出 3 MiB，`cli_run` 返回明确错误（"CLI 输出不完整，已阻止继续操作"），不解析半截输出；前端 parser 对未闭合 JSON 返回"输出不完整"（vitest 覆盖） | 通过 |
| pending journal 恢复链 | `test_recover_rolls_back_pending_journal_preview_then_execute`：构造含真实 before/after 指纹的 pending journal；后续写入被阻塞，preview 报告计划且不修改目标，execute 回滚并消费 journal，重复 recover 幂等 | 通过（事务 fixture；不等同于真实进程强杀） |
| 旧 launcher 首个移动后强杀 | source CLI 事务测试：子进程执行 runtime install，在首个 `claude.ps1` no-overwrite move 完成、after-move 进度尚未落盘时由父进程强杀；pending journal 阻塞新写入，preview 前后快照一致且计划 `restore-moved`，execute 精确还原 `.ps1/.cmd` 与此前所有 runtime 写入并清理 journal/lock/备份 | macOS 本地通过；`test_forced_kill_after_first_legacy_launcher_move_recovers_exactly`。Windows source-CLI 候选门禁已在 CI run `31810727817` 通过；不等同于已安装冻结 sidecar 或实体机 UI 验收 |
| journal after 证据持久化 | `test_transaction_helpers_persist_after_evidence_and_reject_later_edit`：生产事务 helper 把 mutation 后指纹写回实际 journal；随后第三方修改会被识别为未知修改并失败关闭 | 通过 |
| recover 预览纯只读 | `snapshot_tree` 对整个隔离 HOME 比较文件内容、mode 与 mtime；可恢复、多步同路径与 marker 场景 preview 前后快照一致 | 通过 |
| 同路径多步逆序恢复 | `test_recover_repeated_writes_use_virtual_reverse_state`：同一路径 `A → B → C` 的 preview 与 execute 均按 `C → B → A` 判定，最终恢复原内容 | 通过 |
| 写入故障自动回滚 | `test_install_failure_rolls_back_and_recovers_clean`：在 mutation 中注入 `OSError`，验证原内容恢复、journal/lock 清理、备份保留 | 通过（故障注入；不等同于 `SIGKILL`） |
| committed journal 不反撤 | `test_committed_journal_is_never_reversed` / `test_committed_launcher_migration_is_never_reversed` / `test_crash_after_commit_window_is_consumed_by_next_write`：committed 文件写入和 launcher 迁移结果保持，残留 journal 只被消费 | 通过 |
| 活锁拒绝与 stale lock 回收 | 存活进程持有 `.keysmith.lock` 时写入失败关闭；死 PID stale lock 可由下一次受控操作回收 | 通过 |
| 原子临时残留失败关闭 | 强杀可能遗留的 `.<target>.keysmith-tmp-*.tmp` 会让 status 标记 recovery-required、阻塞后续写入；recover preview 只读列出计划，execute 只清理专属临时残留，不碰其它文件 | 通过 |
| 全局写租约边界 | vitest：execute 走独占租约、并发写拒绝、preview/读操作走共享租约不被误锁、后端同步抛错时租约释放（`api.test.js` / `store.test.js`，113 passed 内） | 通过 |

真实进程强杀 E2E 已在隔离 HOME 对冻结 sidecar 执行：监控到 journal 已持久化至少 1 个 write step 后对整个进程组发送 `SIGKILL`（进程返回 `-9`）；随后 `status.recovery_required=true`，新写入 exit 1，recover preview 前后全树快照一致，execute 精确恢复被跟踪文件并清理 journal、stale lock 与临时残留，最终 hash 全部回到强杀前状态。

### GUI 运行时（macOS 实体机，release `.app`，隔离环境）

| 项目 | 证据 | 结果 |
|---|---|---|
| Dashboard | release `.app` 在隔离环境显示 runtime=`bundled`、CLI `v7`、GUI beta 版本与 source commit | 通过 |
| Deploy 向导 | GUI 内完成 user runtime preview → confirm → execute；preview 前后磁盘零差异，execute 后 wrapper 注入参数由 fake 上游验证 | 通过 |
| Manage restore | GUI 使用 `backups --json` 的绝对 `target_path`；确认框显示正确目标，preview 零写入，execute 后目标 SHA 与所选备份精确一致 | 通过（同时修复只传 basename 会落到根目录的 blocker） |
| Manage uninstall / recover | GUI 内完成 `uninstall --runtime` preview+execute，managed 文件与 wrapper 移除、settings 保留；recover 识别并清理 keysmith 原子临时残留，后续 status 为 `recovery_required:false` | 通过 |
| 操作中关闭 | restore execute 进行中点击关闭，窗口等待操作结束后退出；恢复成功且无 sidecar / lock / journal 残留 | 通过 |
| doctor / backups 不泄漏 | `doctor --json` 键集合固定 9 键；断言输出不含 token / cookie / Bearer / sk- / base_url / ANTHROPIC 字样；`backups --json` 仅含路径、绝对 `target_path` 与指纹元数据，无文件内容 | 通过 |

### Claude Code 包版本目录切换 smoke（隔离 npm prefix）

- 临时安装真实 `@anthropic-ai/claude-code@2.1.231` 与 `2.1.232`，wrapper 首次运行返回 `2.1.231`；移走整个旧版本 prefix 后，不改 wrapper 即动态解析到新 prefix 并返回 `2.1.232`。
- 修复并验证 `status --runtime --json`：旧快路径已消失且 wrapper 其它结构完整时，`shell_wrapper_current=true`、`upstream_exists=true`、`runtime_ready=true`、`upgrade_required=false`。真实 `/Users/ethan/.local/bin/claude` 保持 `2.1.212`，未被调用或修改。
- 证据目录：`/tmp/ks-claude-switch.c6tIaH`；仅执行 `claude --version`，无登录、凭证或模型请求。

## 二、发布前仍须补齐的验证（未完成不得外发）

### macOS ARM64 实体机

- [ ] 从干净（或新建隔离）账户打开未签名 `.app` / `.dmg`，确认 Gatekeeper 提示文案可接受并写入发布说明（当前 `spctl` 拒绝状态见上文，需人工记录用户视角文案）。
- [ ] 用户安装的真实 Claude Code 升级（版本目录切换）后 wrapper 仍可用；上方仅有隔离 npm prefix 的真实包版本切换 smoke，不能替代此项。

### Windows x64 原生环境

`.github/workflows/gui-release-candidate.yml`（main PR 自动验证；合并后以 `expected_sha` 手动触发正式候选；`permissions: contents: read`，只上传 artifact，不打 tag、不建 Release）已在 GitHub 托管 Windows x64 runner 完成原生构建与自动化安装链。托管 runner 证明安装包和关键失败关闭路径可执行，不等同于真实用户可见 UI、SmartScreen 或无 WebView2 机器验收：

- [x] 原生 sidecar `--version` smoke + NSIS currentUser 安装器产出；静默 currentUser 安装/卸载后无安装目录或卸载注册表残留。
- [x] 已安装冻结 sidecar 完成 runtime install/uninstall、PowerShell 5.1 / 7 wrapper 实际加载、scoped restore preview/execute、原子残留 recover 与 doctor/backups 隐私检查。
- [x] GUI 进程启动并保持存活，第二实例由 single-instance guard 退出；此项只证明进程链，不代表页面视觉与交互验收。
- [x] Windows Rust 原生测试覆盖 `taskkill /T /F` 杀父子进程树与 2 MiB 输出超限失败关闭。
- [ ] Windows 实体机可见 UI：安装 → Dashboard/sidecar 探测 → Deploy → Manage uninstall/restore/recover → 操作中关闭。
- [ ] Windows 实体机旧 launcher 迁移与同名冲突路径（`~/.local/bin/claude.ps1` / `claude.cmd`）；托管 runner 仅将 source-CLI 迁移/冲突测试设为自动门禁。
- [ ] WebView2 bootstrapper 在无 WebView2 机器上静默安装。
- [ ] 未签名 SmartScreen 提示文案确认并写入发布说明。
- [ ] Windows 实体机事务中途强杀后的 pending journal 阻塞、只读 preview 与精确恢复 E2E；托管 runner 另有 source-CLI 首次 launcher 移动后强杀测试，不等同于已安装冻结 sidecar 或可见 UI 验收。

## 三、发布政策与边界声明

- 本分支仅产出源码、文档与候选构建链；发行打包只用 `npm run bundle`。
- 候选产物（DMG / NSIS / sidecar / `SHA256SUMS` / `BUILD_INFO.json`）只存在于本地候选目录与 CI artifact，不上传 Release。
- **本次 beta 已接受限制（不单独阻塞 beta）**：无开发者代码签名、无 macOS notarization、无 Windows Authenticode、无自动更新、无 Linux GUI。产物必须明确标记 `unsigned beta`，附 SHA-256、source commit、Gatekeeper / SmartScreen 实测提示与人工安装说明；不得暗示系统信任链或自动更新能力已经具备。
- **真正的 beta 发布门禁**：第二节全部未完成验证完成并留存证据，两个目标平台的 main 候选产物与元数据可复核，发布说明完整披露上述限制；任何外发、tag 或 Release 仍需单独明确授权。
- 若后续改为稳定版或默认面向普通用户分发，macOS Developer ID + notarization 与 Windows Authenticode 应升级为对应平台发布门禁；自动更新仍是独立产品能力，不在本 beta 承诺内。
- 发布采用同批次双 Release：`v7`（正式，CLI）与 `desktop-v0.1.0-beta.1`（Pre-release，GUI beta），指向同一最终 main commit；第二节全部条目勾选并记录前，`0.1.0-beta.1` 不得对任何外部渠道发布。
