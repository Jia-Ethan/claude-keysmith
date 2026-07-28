<!-- markdownlint-disable MD013 MD033 MD041 -->

<h1 align="center">claude-keysmith</h1>

<p align="center">
  Claude Code 指令文件部署：可管理的 <code>CLAUDE.md</code> import block，及可选的 user-scope runtime wrapper。
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装 / Agent install</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Prompt v4.0" src="https://img.shields.io/badge/prompt-v4.0-0099CC">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

## 简体中文

### 这是什么

`claude-keysmith` 是 Claude Code 的本地指令部署工具：它把一份 Markdown 指令保存到 keysmith 管理目录，并在 `CLAUDE.md` 或 `CLAUDE.local.md` 中插入可识别、可卸载的 import block。

可选的 `--runtime` 会额外对齐 `settings.json` 的 `systemPrompt`，并在 `~/.zshrc` 安装 managed `claude()` wrapper，使每次 shell 调用自动带上 `--system-prompt-file` 与 `--append-system-prompt-file`。

默认只预览；显式传入 `--yes` 才写入。写入前备份，卸载时只移除自己的 block 和文件。

> [!WARNING]
> user scope 的 import block 会影响加载 `~/.claude/CLAUDE.md` 的新会话；`--runtime` 还会影响通过 managed shell wrapper 启动的后续会话。先阅读 [`examples/claude-project-rules.md`](examples/claude-project-rules.md) 和 [`examples/claude-append-prompt.md`](examples/claude-append-prompt.md)，运行 dry-run 确认路径与变更后，再使用 `--yes`。本工具不修改二进制、网络、MCP 或凭证，也不承诺覆盖 Claude Code、模型提供方或 API 网关的策略。

### 快速开始（macOS / Linux）

```bash
# 1. 先预览项目级部署；默认不写入
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo

# 2. 确认后才写入
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes

# 3. 检查状态
python3 claude-instruct.py status \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --json
```

需要 user-scope runtime 时：

```bash
python3 claude-instruct.py install --scope user --runtime       # 先预览
python3 claude-instruct.py install --scope user --runtime --yes
source ~/.zshrc
python3 claude-instruct.py doctor --json
```

不要用 `curl | python` 直接执行；先下载或 clone 仓库、检查脚本与示例，再运行。

### 它会改哪些文件

| 路径 | 会发生什么 |
| --- | --- |
| `~/.claude/CLAUDE.md`、`<repo>/CLAUDE.md` 或 `<repo>/CLAUDE.local.md` | 插入或替换一个同名 managed import block；已有文件先备份 |
| 相邻的 `keysmith/<name>.md` 或 `.claude/keysmith/<name>.md` | 新建，或先备份再替换 |
| `~/.claude/keysmith/system-prompt.md`、`append-prompt.md` | 仅 `--runtime`：新建或备份后替换 |
| `~/.claude/settings.json` | 仅 `--runtime`：对齐顶层 `systemPrompt`；使用 `--max-tokens` 时才更新该字段；其余字段保留 |
| `~/.zshrc` | 仅 `--runtime`：插入或替换一个带边界标记的 managed `claude()` wrapper；已有文件先备份 |

完整所有权、settings 更新与恢复语义见 [`docs/reference.md`](docs/reference.md)。

### 撤销

```bash
# 项目级：先预览，再加 --yes
python3 claude-instruct.py uninstall \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules

# user-scope runtime：移除 keysmith prompt 文件和 managed wrapper
python3 claude-instruct.py uninstall --scope user --runtime --yes
```

`uninstall --runtime` 不自动恢复 `settings.json` 的旧 `systemPrompt`，避免覆盖安装后由其他工具或用户写入的配置。需要恢复时，从安装前生成的 timestamp 备份显式执行：

```bash
python3 claude-instruct.py restore \
  --target ~/.claude/settings.json \
  --backup ~/.claude/settings.json.bak_YYYYMMDD_HHMMSS_pre_runtime \
  --yes
```

### 出问题了怎么办

| 现象 | 应该做的事 |
| --- | --- |
| 不确定会改什么 | 不加 `--yes` 运行同一条 `install` / `uninstall`，检查 dry-run 输出 |
| import block 或文件状态异常 | 运行 `status --scope … --json`，确认目标路径、block 与指令文件 |
| runtime 看起来没有生效 | `source ~/.zshrc` 后运行 `doctor --json`，确认 prompt 文件、settings 对齐与 managed wrapper |
| 需要回滚 | 指定对应的 timestamp 备份运行 `restore`；恢复前工具会再为当前文件创建备份 |

### 兼容性与限制

- 推荐 Python 3.8+；runtime wrapper 当前写入 `~/.zshrc`，适用于 zsh。
- 只管理 `claude-keysmith` 自己插入的 HTML 注释 block，不覆盖用户其余 memory 内容。
- 不管理 Claude Code 二进制、运行中进程、网络、MCP、token、cookie、Base URL、hooks 或 permissions。
- 不验证某个既有会话是否重新加载指令；部署后启动新会话并做实际 smoke test。
- 备份不会自动删除；确认无需回滚后再手动清理。

### 参与贡献

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

智能体安装流程见 [`docs/agent-install.md`](docs/agent-install.md)；文件所有权和完整运行时参考见 [`docs/reference.md`](docs/reference.md)。

### 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex CLI versioned instruction deployment.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code managed import-block installer.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build `AGENTS.md` installer.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode true system-role runtime entrypoint.
- [role-keysmith](https://github.com/Jia-Ethan/role-keysmith) — JD-matched Chinese resume rewriting skill.
