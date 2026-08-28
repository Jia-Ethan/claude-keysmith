<!-- markdownlint-disable MD013 -->
# 平台支持矩阵

桌面客户端 `claude-keysmith` GUI `0.1.0-beta.2`（channel `beta`，未签名 Pre-release）的目标产物与验收状态。配置存在 ≠ 验收通过；Windows 产物不能在 macOS worktree 本机构建或运行，原生构建与自动化安装链由 GitHub 托管 Windows x64 runner 验证，两平台用户可见行为由实体机验收补齐。

## 产物矩阵

| 平台 | 产物 | 配置 | 状态 |
|---|---|---|---|
| macOS Apple Silicon（`aarch64-apple-darwin`） | `.app` + `.dmg` | `tauri.macos.conf.json`（targets）+ `tauri.bundle.conf.json`（`externalBin`） | 候选构建、核心 GUI、操作中关闭、强杀恢复、真实 Claude 升级与 Gatekeeper 用户路径均通过，见 [`beta-acceptance.md`](beta-acceptance.md) |
| Windows x64（`x86_64-pc-windows-msvc`） | NSIS currentUser 安装器，WebView2 `downloadBootstrapper`（silent） | `tauri.windows.conf.json`（`allowDowngrades: false`）+ `tauri.bundle.conf.json`（`externalBin`） | 原生 CI 与实体机均通过：安装/卸载、可见 UI、冻结 sidecar、旧 launcher、restore/recover、操作中关闭、强杀恢复、无 WebView2、SmartScreen 与单实例 |
| Linux | 无 GUI 产物 | 无 | 不支持（CLI 继续支持） |

两种受支持平台都只用 `cd gui && npm run bundle` 生成发行产物。该入口先原生构建 sidecar，再加载打包 overlay 启用 bundle 和 `externalBin`；裸 Tauri 构建不是发行打包入口。

## `desktop-v0.1.0-beta.2` 的发布门禁

实体机门禁已由维护者于 2026-08-15 确认全部通过；外发前继续强制核对候选可追溯性与发布授权：

1. **macOS beta 验收**：GUI Dashboard、Deploy、Manage、操作中关闭、真实进程强杀恢复、用户安装路径的 Claude 升级与 Gatekeeper 人工放行路径均已完成。
2. **Windows 原生验收**：GitHub 托管 runner 已通过 sidecar/NSIS 构建、静默 install/uninstall、PowerShell wrapper、restore/recover、隐私、GUI 进程、单实例、超时杀树与输出超限；实体机已补齐可见 UI、操作中关闭、旧 launcher、事务强杀恢复、无 WebView2 与 SmartScreen 路径。
3. **候选可追溯性**：PR 验证 artifact 固定为 `release_eligible:false`；合并后必须从精确 main SHA 重新生成两端 `release_eligible:true` 候选，并复核安装器、sidecar、`BUILD_INFO.json`、LF-only `SHA256SUMS`、版本、source commit、目标架构及签名状态。
4. **发布授权**：本轮可以完成分支、PR、合并与候选 artifact；创建 tag / GitHub Release 前必须停下取得明确授权。

完整逐项状态以 [`beta-acceptance.md`](beta-acceptance.md) 为准。

## 本次未签名 beta 已接受的限制

以下能力尚未提供，但在 Release 标题和产物名称明确标记 `unsigned beta`、提供 SHA-256，并在本文保留人工安装说明的前提下，**不单独阻塞 `desktop-v0.1.0-beta.2`**：

1. **代码签名 / notarization / Authenticode**：均未配置发行身份。macOS 候选使用完整 ad-hoc 签名（无 hardened runtime），`codesign --verify --deep --strict` 通过但 `spctl` 拒绝；Windows 安装器、GUI、sidecar 与 uninstaller 均为 `NotSigned`，两平台人工放行路径已完成实体机验收。
2. **自动更新**：未实现，无 updater 配置；本 beta 仅支持用户手动下载、校验并安装后续版本。
3. **Linux GUI**：不在本 beta 支持范围，Linux 继续使用 CLI。

若后续转为稳定版或面向普通用户的默认分发，macOS Developer ID + notarization 与 Windows Authenticode 应升级为对应平台发布门禁。自动更新是独立产品能力，除非后续稳定版政策另行要求，否则不与签名门禁混为一项。

## 未签名预发布版安装

下载后先使用 Release 附带的 `SHA256SUMS` 校验安装包，再按平台安装：

- **macOS Apple Silicon**：打开 `.dmg` 并将应用拖入 Applications。首次启动若被 Gatekeeper 拦截，在 Finder 中按住 Control 点击应用并选择“打开”；仍被阻止时，前往“系统设置 → 隐私与安全性”，确认目标应用后选择“仍要打开”。系统版本不同可能使用近似文案。
- **Windows x64**：先用 `Get-FileHash .\claude-keysmith-desktop-0.1.0-beta.2-windows-x64-unsigned-setup.exe -Algorithm SHA256` 校验安装器，再运行该文件。若 SmartScreen 拦截，核对文件名与 SHA-256 后选择“更多信息 → 仍要运行”。无 WebView2 的机器会由安装器静默下载 bootstrapper，因此安装阶段需要可访问 Microsoft 下载服务的网络。

## CLI 平台支持（背景，不属于 GUI 产物）

- 运行时 wrapper：macOS / Linux zsh，Windows PowerShell 5.1 / PowerShell 7（v7 unix wrapper 每次调用动态重解析上游入口，见 [`../CHANGELOG.md`](../CHANGELOG.md) 与 [`reference.md`](reference.md)）。
- CMD 与 Git Bash 不属于 managed wrapper 支持范围。
- GUI 内嵌的 CLI sidecar 与源码 CLI 行为一致（同一份 `claude-instruct.py` 冻结打包）。
