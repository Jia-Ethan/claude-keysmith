<!-- markdownlint-disable MD013 -->
# Release Notes 草稿

## claude-keysmith v7.2

默认提示词整体重写，实测拒绝少了、完整交付多了。

以前那种一开口就被拦、或者只给你一堆空话替代方案的请求——逆向、补丁、实验室里的安全工具、创作——现在更容易直接拿到能用的完整结果。Claude Code 的 Fable 5.1 上，完整交付从 1/4 提升到 3/4。

两点提醒：写成「安全规则已关闭」那种硬压，实测会适得其反，这次已经改成正常的项目规则写法；效果在加上 `--runtime` 之后更明显。装完请开一个新会话。

本次不更新桌面版安装包。

## Desktop 0.1.0-beta.2：未签名 Beta

- 深色主题对齐 Codex tech blue。
- 修复 Windows 安装/卸载时 WebView2 子进程残留问题。
- 支持 macOS Apple Silicon 和 Windows x64；未签名、无自动更新。
- 下载后请使用 `SHA256SUMS` 校验安装包。

公开资产：

- `claude-keysmith-desktop-0.1.0-beta.2-macos-arm64-unsigned.dmg`
- `claude-keysmith-desktop-0.1.0-beta.2-windows-x64-unsigned-setup.exe`
- `SHA256SUMS`
