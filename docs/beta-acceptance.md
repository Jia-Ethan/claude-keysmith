<!-- markdownlint-disable MD013 -->
# Beta 验收清单（`0.1.0-beta.1`）

本文区分"已在开发机本地验证"与"发布前必须在实体机/原生 runner 验证"两类。**本任务不发布任何产物**；GUI 是未签名的 beta，外发前必须完成第二节全部条目。

## 一、已在本地（macOS 开发机）验证

| 项目 | 命令 / 方式 | 结果 |
|---|---|---|
| CLI 语法 | `python3 -m py_compile claude-instruct.py` | 通过 |
| CLI 测试套件 | 隔离 `HOME` / `CLAUDE_KEYSMITH_HOME` 后运行 `python3 -m pytest tests`（含 `test_json_contract.py`、`test_transaction_recovery.py`、`test_controlled_restore.py`、`test_wrapper_and_max_tokens.py`） | 通过（121 passed） |
| 前端测试 | `cd gui && npm test`（vitest：parser / store / windowLifecycle / 写互斥 / 打包配置 / 视图逻辑） | 通过（11 个测试文件，113 passed） |
| Rust 门禁 | `cd gui/src-tauri && cargo fmt --check && cargo check --locked && cargo test --locked` | 通过（7 passed；干净检出无需预先构建 sidecar） |
| sidecar 构建 | `npm run build:sidecar`（PyInstaller onefile，含 `--version` smoke） | 通过（本机 `aarch64-apple-darwin`，sidecar 报 `claude-keysmith v7`） |
| 前端生产构建 | `npm run build`（vite → `dist/`） | 通过 |
| macOS 发行打包 | `npm run bundle`，随后 `hdiutil verify` 并挂载检查内嵌 sidecar | 通过（`.app` + `.dmg`；DMG 校验有效；内嵌 arm64 sidecar 报 `claude-keysmith v7`） |
| 隔离 HOME smoke | 以临时 `HOME` 运行 install/status/backups/restore/recover/uninstall `--json` 全流程 | 通过（本文档 JSON 示例即来自该流程，已脱敏） |

## 二、发布前必须在实体机验证（PENDING，未通过不得外发）

以下条目在任何已运行验证中都**不**包含，必须逐项在目标实体机/原生 runner 上执行并记录结果：

### macOS ARM64 实体机

- [ ] 从干净（或隔离）账户打开未签名 `.app` / `.dmg`，确认 Gatekeeper 提示文案可接受并在发布说明中写明。
- [ ] Dashboard 正确探测 sidecar（runtime=`bundled`）与 CLI 版本 `v7`。
- [ ] Deploy 向导完整执行 user scope runtime 安装；新 shell 会话中 `claude` wrapper 生效（`--system-prompt-file` / `--append-system-prompt-file` 注入）。
- [ ] Manage 页执行 uninstall（含 runtime）、从受控备份 restore、recover；每一步 preview → confirm → execute 报告正确。
- [ ] 操作进行中关闭窗口：退出排队，操作完成后窗口才销毁；无孤儿 CLI 进程（`ps` 验证进程树被杀）。
- [ ] Claude Code 升级（版本目录切换）后 wrapper 仍可用（v7 动态重解析路径的实际验证）。

### Windows x64 实体机 / 原生 CI runner（全部为 PENDING）

- [ ] 原生 runner 上 `npm run bundle` 成功：先构建 `x86_64-pc-windows-msvc` sidecar 并通过 `--version` smoke，再产出 NSIS currentUser 安装器；WebView2 bootstrapper 在无 WebView2 的机器上能静默安装运行时。
- [ ] 安装 → 启动 → sidecar 探测 → Deploy（user runtime，PowerShell profile wrapper，`. $PROFILE` 生效）。
- [ ] uninstall / restore / recover / 退出行为同 macOS 清单。
- [ ] 旧 launcher 迁移路径（存在 `~/.local/bin/claude.ps1`/`claude.cmd` 时）按 dry-run 计划执行；未知同名文件触发冲突而非覆盖。
- [ ] 未签名 SmartScreen 提示文案确认并写入发布说明。

### 两平台共同

- [ ] 超时杀进程树的实际验证（人为挂起 CLI，确认整棵进程树被清理）。
- [ ] 2 MiB 输出截断的失败关闭路径在 UI 中表现为明确错误而非半截报告。
- [ ] 中断恢复：写操作中途强杀 GUI + CLI，重启后 `recovery-required` 健康态出现，`recover` 预览/执行完成回滚。

## 三、发布边界声明

- 本 worktree 仅产出源码与文档；发行打包只用 `npm run bundle`，并在 worktree 外执行。
- 无代码签名、无 notarization/Authenticode、无自动更新、无 Linux GUI——这些是发布前显式门槛（见 [`platform-support.md`](platform-support.md)）。
- 第二节全部条目勾选并记录前，`0.1.0-beta.1` 不得对任何外部渠道发布。
