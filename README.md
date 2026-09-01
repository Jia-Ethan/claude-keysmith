<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img src="docs/assets/readme/claude-keysmith-preview.png" alt="Illustrative claude-keysmith install preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>Illustrative preview / 示意预览；实际路径与输出以本机 dry-run 为准。</em></p>

<h1 align="center">claude-keysmith</h1>

<p align="center">先预览、再写入、可撤销的 Claude Code 指令部署工具。</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装</a> ·
  <a href="docs/desktop-gui.md">Desktop</a> ·
  <a href="docs/privacy-security.md">Privacy</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## 简体中文

Keysmith 系列为本地 AI 工具**安全部署、验证和撤销**自定义指令。`claude-keysmith` 把一份 Markdown 存进 keysmith 目录，并在 `CLAUDE.md` / `CLAUDE.local.md` 插入可识别、可卸载的 import block。

> [!WARNING]
> **项目 / local scope** 只影响该仓库；**user scope** 会影响加载 `~/.claude/CLAUDE.md` 的新会话。`--runtime` 还会对齐 `settings.json` 的 `systemPrompt`，并安装 managed shell wrapper。默认只预览，显式 `--yes` 才写入。先阅读 [`examples/claude-project-rules.md`](examples/claude-project-rules.md)、[`examples/claude-append-prompt.md`](examples/claude-append-prompt.md) 和 [`docs/privacy-security.md`](docs/privacy-security.md)。

### 选择哪个 Keysmith

| 项目 | 目标工具 | 部署面 | 稳妥安装 | Desktop |
| --- | --- | --- | --- | --- |
| [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) | Codex | 全局 `~/.codex` 指令 | 稳定 CLI Release | 未签名 Beta |
| **[claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith)** | Claude Code | 项目 / 用户 `CLAUDE.md` import | 稳定 v7.1 源码 tag | 未签名 Beta |
| [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) | Grok Build | 全局 `~/.grok/rules`（不改 `AGENTS.md`） | 稳定 CLI Release | 未签名 Beta |
| [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) | ZCode App | 用户目录 system-role + wrapper | 仅源码 | 无 |

### 安装方式

1. **稳妥：稳定 v7.1 源码 CLI。** 没有独立 CLI 安装包；按下方命令固定 clone `v7.1` tag，再运行 `claude-instruct.py`。不要 `curl | python`。
2. **更易用：未签名 Desktop Beta。** 见 [desktop-v0.1.0-beta.2](https://github.com/Jia-Ethan/claude-keysmith/releases/tag/desktop-v0.1.0-beta.2)：macOS Apple Silicon DMG 与 Windows x64 NSIS，内嵌 v7.1 CLI。无 Linux GUI、无自动更新、无签名。步骤见 [`docs/platform-support.md`](docs/platform-support.md)。

### 快速开始（稳定 v7.1）

```bash
git clone --branch v7.1 --depth 1 https://github.com/Jia-Ethan/claude-keysmith.git
cd claude-keysmith
python3 claude-instruct.py --version  # claude-keysmith v7.1
python3 claude-instruct.py install --scope project --project-dir /path/to/repo
python3 claude-instruct.py install --scope project --project-dir /path/to/repo --yes
python3 claude-instruct.py status --scope project --project-dir /path/to/repo
```

可选 user-scope runtime：先 `install --scope user --runtime` 预览，再加 `--yes`。macOS / Linux 随后 `source ~/.zshrc`；Windows PowerShell 用 `python .\\claude-instruct.py` 并 `. $PROFILE`。

### 会修改什么

| 路径 | 会发生什么 |
| --- | --- |
| `CLAUDE.md` 或 `CLAUDE.local.md` | 插入或替换同名 managed import block |
| 相邻 `keysmith/<name>.md` | 新建，或先备份再替换 |
| `~/.claude/settings.json`、shell profile | 仅 `--runtime`：对齐 `systemPrompt` 并写入 managed wrapper |

不修改 Claude 二进制、MCP、hooks、permissions 或凭证。完整表见 [`docs/reference.md`](docs/reference.md)。

### 如何撤销

```bash
# 项目级卸载先预览，确认后加 --yes
python3 claude-instruct.py uninstall --scope project --project-dir /path/to/repo
python3 claude-instruct.py uninstall --scope user --runtime --yes
python3 claude-instruct.py restore --target PATH --backup PATH --yes
```

v7.1 提供备份枚举和中断事务恢复：

```bash
python3 claude-instruct.py backups --scope user --json
python3 claude-instruct.py recover --scope user
python3 claude-instruct.py recover --scope user --yes
```

`uninstall --runtime` 不自动回滚 `settings.json` 的 `systemPrompt`；可对已知的安装前备份执行 `restore`。写操作中断时，先用 `recover` 预览，再加 `--yes`。

### 平台与 Beta 限制

- CLI：Python 3.8+；wrapper 支持 macOS / Linux zsh 与 Windows PowerShell 5.1 / 7。CMD、Git Bash 不在正式范围。
- Desktop：仅 macOS Apple Silicon 与 Windows x64；未签名，可能触发 Gatekeeper / SmartScreen。
- 版本与产物以 [Releases](https://github.com/Jia-Ethan/claude-keysmith/releases) 和 [`docs/platform-support.md`](docs/platform-support.md) 为准。

### 进阶文档

- Runtime wrapper / settings：[`docs/reference.md`](docs/reference.md)
- Journal、锁、恢复：[`docs/transaction-recovery.md`](docs/transaction-recovery.md)
- JSON 契约：[`docs/json-contract.md`](docs/json-contract.md)
- Desktop / 智能体安装：[`docs/desktop-gui.md`](docs/desktop-gui.md) · [`docs/agent-install.md`](docs/agent-install.md)

### 贡献、安全与系列

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

安全边界见 [`docs/privacy-security.md`](docs/privacy-security.md)。官方反馈：[GitHub Discussions](https://github.com/Jia-Ethan/claude-keysmith/discussions/13)；社区交流：[LINUX DO](https://linux.do)。

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex 全局指令
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code 可卸载 import block
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build home rules（`~/.grok/rules/99-keysmith.md`，不改 `AGENTS.md`）
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode App system-role 入口（仅源码，无 Desktop）
