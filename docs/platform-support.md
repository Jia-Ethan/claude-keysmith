<!-- markdownlint-disable MD013 -->
# 平台支持矩阵

桌面客户端 `claude-keysmith` GUI `0.1.0-beta.1`（channel `beta`，未签名，未发布）的目标产物与验收状态。配置存在 ≠ 验收通过；Windows 产物在本 worktree 内**无法**本机构建或运行，必须等待原生 Windows runner 验收。

## 产物矩阵

| 平台 | 产物 | 配置 | 状态 |
|---|---|---|---|
| macOS Apple Silicon（`aarch64-apple-darwin`） | `.app` + `.dmg` | `tauri.macos.conf.json`（targets）+ `tauri.bundle.conf.json`（`externalBin`） | 核心 GUI / 强杀恢复验收通过；Gatekeeper 用户视角提示仍待记录，见 [`beta-acceptance.md`](beta-acceptance.md) |
| Windows x64（`x86_64-pc-windows-msvc`） | NSIS currentUser 安装器，WebView2 `downloadBootstrapper`（silent） | `tauri.windows.conf.json`（`allowDowngrades: false`）+ `tauri.bundle.conf.json`（`externalBin`） | **PENDING**：需要原生 Windows runner 构建 + 实体机/CI 验收，未通过前不得发布 |
| Linux | 无 GUI 产物 | 无 | 不支持（CLI 继续支持） |

两种受支持平台都只用 `cd gui && npm run bundle` 生成发行产物。该入口先原生构建 sidecar，再加载打包 overlay 启用 bundle 和 `externalBin`；裸 Tauri 构建不是发行打包入口。

## `desktop-v0.1.0-beta.1` 的实际发布门禁

以下事项直接决定未签名 beta 能否外发，不得在取得证据前表述为已完成：

1. **macOS beta 验收**：GUI Dashboard、Deploy、Manage、操作中关闭与真实进程强杀恢复 E2E 已完成；仍需记录带 quarantine 的 Gatekeeper 用户视角提示及人工安装步骤。
2. **Windows 原生验收**：sidecar 构建（PyInstaller 仅支持本机原生构建，脚本对跨平台直接报错）、NSIS 打包、install/deploy/uninstall/restore/退出行为、失败关闭专项与 SmartScreen 提示，都必须在原生 Windows x64 runner / 实体机验证。
3. **候选可追溯性**：两个平台均需产出可复核的安装器、sidecar、`BUILD_INFO.json` 与 `SHA256SUMS`，并确认版本、source commit、目标架构及 `signed:false` 与实际一致。
4. **发布授权**：本轮可以完成分支、PR、合并与候选 artifact；创建 tag / GitHub Release 前必须停下取得明确授权。

完整逐项状态以 [`beta-acceptance.md`](beta-acceptance.md) 为准。

## 本次未签名 beta 已接受的限制

以下能力尚未提供，但在发布说明和产物名称明确标记 `unsigned beta`、给出校验信息与人工安装说明的前提下，**不单独阻塞 `desktop-v0.1.0-beta.1`**：

1. **代码签名 / notarization / Authenticode**：均未配置发行身份。macOS 候选使用完整 ad-hoc 签名（无 hardened runtime），`codesign --verify --deep --strict` 通过但 `spctl` 拒绝；Windows 安装器预期无 Authenticode，实际 SmartScreen 文案仍为 PENDING。
2. **自动更新**：未实现，无 updater 配置；本 beta 仅支持用户手动下载、校验并安装后续版本。
3. **Linux GUI**：不在本 beta 支持范围，Linux 继续使用 CLI。

若后续转为稳定版或面向普通用户的默认分发，macOS Developer ID + notarization 与 Windows Authenticode 应升级为对应平台发布门禁。自动更新是独立产品能力，除非后续稳定版政策另行要求，否则不与签名门禁混为一项。

## CLI 平台支持（背景，不属于 GUI 产物）

- 运行时 wrapper：macOS / Linux zsh，Windows PowerShell 5.1 / PowerShell 7（v7 unix wrapper 每次调用动态重解析上游入口，见 [`../CHANGELOG.md`](../CHANGELOG.md) 与 [`reference.md`](reference.md)）。
- CMD 与 Git Bash 不属于 managed wrapper 支持范围。
- GUI 内嵌的 CLI sidecar 与源码 CLI 行为一致（同一份 `claude-instruct.py` 冻结打包）。
