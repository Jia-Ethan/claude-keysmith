<!-- markdownlint-disable MD013 -->
# 平台支持矩阵

桌面客户端 `claude-keysmith` GUI `0.1.0-beta.1`（channel `beta`，未签名，未发布）的目标产物与验收状态。配置存在 ≠ 验收通过；Windows 产物在本 worktree 内**无法**本机构建或运行，必须等待原生 Windows runner 验收。

## 产物矩阵

| 平台 | 产物 | 配置 | 状态 |
|---|---|---|---|
| macOS Apple Silicon（`aarch64-apple-darwin`） | `.app` + `.dmg` | `tauri.macos.conf.json`（targets）+ `tauri.bundle.conf.json`（`externalBin`） | 就绪；本机可构建，实体机验收见 [`beta-acceptance.md`](beta-acceptance.md) |
| Windows x64（`x86_64-pc-windows-msvc`） | NSIS currentUser 安装器，WebView2 `downloadBootstrapper`（silent） | `tauri.windows.conf.json`（`allowDowngrades: false`）+ `tauri.bundle.conf.json`（`externalBin`） | **PENDING**：需要原生 Windows runner 构建 + 实体机/CI 验收，未通过前不得发布 |
| Linux | 无 GUI 产物 | 无 | 不支持（CLI 继续支持） |

两种受支持平台都只用 `cd gui && npm run bundle` 生成发行产物。该入口先原生构建 sidecar，再加载打包 overlay 启用 bundle 和 `externalBin`；裸 Tauri 构建不是发行打包入口。

## 明确的后续门槛（follow-up gates）

以下事项**均未实现**，是发布前的显式门槛，不得在任何材料中表述为已完成：

1. **Windows 原生验收**：sidecar 构建（PyInstaller 仅支持本机原生构建，脚本对跨平台直接报错）、NSIS 打包、install/deploy/uninstall/restore/退出行为，都必须在原生 Windows x64 runner 上验证。
2. **代码签名 / notarization / Authenticode**：均未配置。macOS `.dmg` 未公证（Gatekeeper 会提示）；Windows 安装器无 Authenticode 签名（SmartScreen 会提示）。
3. **自动更新**：未实现，无 updater 配置。
4. **公开发布**：本 worktree 不做任何发布；beta 制品是否外发由 [`beta-acceptance.md`](beta-acceptance.md) 的验收结果决定。

## CLI 平台支持（背景，不属于 GUI 产物）

- 运行时 wrapper：macOS / Linux zsh，Windows PowerShell 5.1 / PowerShell 7（v7 unix wrapper 每次调用动态重解析上游入口，见 [`../CHANGELOG.md`](../CHANGELOG.md) 与 [`reference.md`](reference.md)）。
- CMD 与 Git Bash 不属于 managed wrapper 支持范围。
- GUI 内嵌的 CLI sidecar 与源码 CLI 行为一致（同一份 `claude-instruct.py` 冻结打包）。
