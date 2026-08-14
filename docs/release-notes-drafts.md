<!-- markdownlint-disable MD013 -->
# Release Notes 草稿（未发布）

发布方式：同批次双 Release，两者指向**同一个最终 main commit**。

| Release | tag | 类型 | 内容 |
|---|---|---|---|
| claude-keysmith v7 | `v7` | 正式 Release | CLI（JSON 契约、事务恢复层、wrapper 动态重解析） |
| Desktop GUI 0.1.0-beta.1 | `desktop-v0.1.0-beta.1` | **Pre-release** | 未签名桌面客户端 beta |

以下为草稿正文；发布日期、产物链接与 SHA-256 在实际发布时填入。`desktop-v0.1.0-beta.1` 是明确的未签名 beta：签名、公证、Authenticode 与自动更新缺失属于已接受且必须披露的限制，不替代 [`beta-acceptance.md`](beta-acceptance.md) 第二节中的真实发布门禁。

---

## 草稿：v7（正式 CLI Release）

### claude-keysmith v7

CLI 稳定性与可编程性版本。

- **`claude-keysmith/v1` JSON 契约**：`install` / `status` / `doctor` / `uninstall` / `restore` 支持 `--json` 稳定输出；写操作区分 `preview` 与 `execute`（`--yes`），统一携带 `actions` / `warnings` / `blockers` / `backups` 证据；argparse usage error 也输出契约 JSON。新增只读 `backups` 与幂等 `recover` 命令。
- **Durable journal + 写锁**：所有写路径由 scope 本地排他锁与两阶段事务日志保护；中断后 `recover` 预览/执行回滚未提交事务，committed 事务永不反转；活锁、损坏 journal、未知修改一律失败关闭。
- **unix wrapper 动态重解析**：修复 wrapper 将版本目录烙死导致 Claude Code 更新后失效的问题；路径失效时每次调用重新解析，全部失败返回 127。
- **Windows wrapper retry safety**：已启动脚本内部的 CommandNotFound 不再触发候选重试或重复执行。
- `--max-tokens` 正整数校验。

升级：重新运行 `install --scope user --runtime --yes` 即可将 wrapper 迁移到 v7 模板。文档：[`json-contract.md`](json-contract.md)、[`transaction-recovery.md`](transaction-recovery.md)、[`reference.md`](reference.md)。

（发布时补：source commit、`python3 claude-instruct.py --version` 输出）

---

## 草稿：desktop-v0.1.0-beta.1（Pre-release）

### claude-keysmith Desktop 0.1.0-beta.1（未签名 beta）

首个桌面客户端 beta。Tauri 2 + React 19，内嵌与 CLI 同源构建的 PyInstaller sidecar（`claude-keysmith v7`）。

- 页面：Dashboard（sidecar 探测 / 状态）、三步 Deploy 向导、Manage（uninstall / 受控备份 restore / recover / repair）、Settings（zh-CN / en）。
- 每一步写操作都走 CLI JSON 契约的 preview → confirm → execute，失败关闭：超时杀整棵进程树、输出超限拒绝解析、全局写互斥、关闭窗口排队等待在途操作。Manage restore 使用 `backups --json` 返回的绝对目标路径并由 CLI 复核 scope 内 target / backup 精确配对。
- 目标产物：macOS Apple Silicon `.dmg`；Windows x64 NSIS currentUser 安装器 + WebView2 bootstrapper。Windows 原生 CI 构建、静默安装/卸载、冻结 sidecar、PowerShell wrapper、restore/recover、隐私、GUI 进程与单实例 smoke 已通过；实体机可见 UI、SmartScreen、无 WebView2 与事务强杀恢复仍待验收。

**本次 beta 已接受的限制（重要）**：

- 安装包无发行身份签名，且无 macOS notarization / Windows Authenticode。macOS 使用完整 ad-hoc 签名（无 hardened runtime），整包 codesign 校验通过但 `spctl` 拒绝；Windows 安装器、GUI、sidecar 与 uninstaller 均已确认 `NotSigned`，SmartScreen 实际提示仍待实体机验收。发布时必须补充两平台实测文案、人工安装步骤、SHA-256 与 source commit。
- 无自动更新；后续版本需手动下载、校验并安装。无 Linux GUI，Linux 继续使用 CLI。
- 上述限制不单独阻塞这次明确标记为 `Pre-release` / `unsigned beta` 的版本，也不得被描述为已实现。

**发布门禁**：

- [`beta-acceptance.md`](beta-acceptance.md) 第二节全部未完成条目必须完成并留存证据。macOS GUI UI 与真实进程强杀恢复 E2E 已通过；Windows 原生自动化链已通过，剩余门禁集中在 Gatekeeper、真实 Claude 升级与 Windows 实体机用户视角/强杀恢复。
- 两个平台仅发布实际通过验收的 main 候选，且 `release_eligible:true`，`BUILD_INFO.json` / LF-only `SHA256SUMS` 与安装器、sidecar 一致；tag、Release 与外发仍需单独明确授权。
- 发现问题请开 issue。

（发布时补：产物列表、字节数、SHA-256、Gatekeeper / SmartScreen 实测文案、source commit）
