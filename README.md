# claude-keysmith

<p align="center">
  <strong>Claude Code CLAUDE.md import-block installer for local instruction files.</strong>
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude-Code-555555">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-6DB33F">
  <img alt="Status" src="https://img.shields.io/badge/status-local%20tool-0099CC">
</p>

> **Status boundary / 状态边界**
>
> `claude-keysmith` is a small local helper for managing Claude Code `CLAUDE.md` import blocks, separate Markdown instruction files, and an optional user-scope runtime wrapper. It is not a Claude Code fork, does not patch binaries, does not intercept network traffic, does not save credentials, tokens, cookies, or MCP secrets, and does not guarantee that installed instructions will unlock every model behavior on every provider.
>
> `claude-keysmith` 是一个小型本地工具，用来管理 Claude Code `CLAUDE.md` 中的 import 区块、独立 Markdown 指令文件，以及可选的 user-scope runtime 包装层。它不是 Claude Code 分叉版，不修改二进制，不劫持网络，不保存凭证、token、cookie 或 MCP 机密，也不保证安装后在每个供应商/模型上都能突破全部内容策略。

## 复制给智能体安装

把下面这段话复制到 Codex、Claude Code、Cursor Agent 或其他智能体：

```text
请使用 https://github.com/Jia-Ethan/claude-keysmith 帮我安全安装 Claude Code 的 user scope 本地 CLAUDE.md import-block 指令文件，也就是写入 ~/.claude/CLAUDE.md 和 ~/.claude/keysmith/<name>.md。先阅读 README 和脚本，默认只做静态审计和 dry-run，不要直接写入；写入前展示将修改的准确文件路径、备份路径和 import block，并等我确认；确认后先备份再安装。不要修改 Claude Code 二进制、settings、MCP、网络、运行进程，也不要保存任何 token、cookie 或私密配置。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI 本地配置的版本化指令部署工具，支持预览、hook 隔离、中断恢复与分层卸载。 / Versioned instruction deployment for local Codex CLI configuration with preview, hook isolation, interruption recovery, and layered uninstall.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` 的受管理 import-block 安装器，用于本地 Markdown 指令文件。 / Managed Claude Code `CLAUDE.md` import-block installer for local Markdown instruction files.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode App 的受管理 true system-role 入口，通过 agent-server wrapper 将 `system-role.md` 接入 runtime `customSystemPrompt` 的 system-message 路径。 / Managed true system-role entrypoint for ZCode App; an agent-server wrapper routes `system-role.md` into the runtime `customSystemPrompt` system-message path.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build 的全局 `AGENTS.md` 指令部署工具，支持 compat/hook 隔离、中断恢复与分层卸载。 / Global `AGENTS.md` instruction deployment for Grok Build with compat/hook isolation, interruption recovery, and layered uninstall.

---

## Why this exists

Claude Code already supports persistent instructions through `CLAUDE.md`, `CLAUDE.local.md`, project `.claude` files, and `@path/to/import` imports. This tool does not replace that system. It only gives you a safer, repeatable way to place one instruction file under a keysmith-managed directory and insert a small managed import block into the appropriate Claude memory file.

Official references:

- [Claude Code memory / CLAUDE.md](https://docs.anthropic.com/en/docs/claude-code/memory)
- [Claude Code settings scopes](https://docs.anthropic.com/en/docs/claude-code/settings)

---

## 简体中文

### 项目定位

`claude-keysmith` 是 `codex-keysmith` 思路的 Claude Code 版改造。原项目围绕 Codex CLI 的 `model_instructions_file` 与 `~/.codex/config.toml`；本项目不写 Codex 配置，也不写 Claude Code 的真实设置 JSON、token、cookie、MCP 或二进制。

Claude Code 版的核心是：

1. 将指令 Markdown 写入 keysmith 管理目录；
2. 在目标 `CLAUDE.md` 或 `CLAUDE.local.md` 中插入一个可识别、可卸载的 import block；
3. 只管理自己的 block，不覆盖整份用户文件。

### 支持范围

| scope | 被修改的 Claude memory 文件 | 指令文件位置 | import 目标 |
|---|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `~/.claude/keysmith/<name>.md` | `@keysmith/<name>.md` |
| `project` | `<repo>/CLAUDE.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |
| `local` | `<repo>/CLAUDE.local.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |

Managed block example:

```md
<!-- claude-keysmith:start name=claude-project-rules -->
@.claude/keysmith/claude-project-rules.md
<!-- claude-keysmith:end name=claude-project-rules -->
```

### 安全默认值

- 默认 dry-run：没有 `--yes` 时只预览，不写入；如果 `--dry-run` 和 `--yes` 同时出现，`--dry-run` 优先。
- 写入前备份已存在的 `CLAUDE.md` / `CLAUDE.local.md`。
- 覆盖同名 keysmith 指令文件前先备份。
- `uninstall` 只移除同名 managed block，并备份后移除对应 keysmith 指令文件。
- `restore` 会先备份当前 target，再用指定 backup 恢复。
- `--name` 只允许字母、数字、点、下划线、连字符，拒绝路径、绝对路径、`..`、空文件名和空格。
- 默认不修改 `settings.json`、MCP、凭证、二进制或运行中进程；仅当显式传入 `--runtime` 时，才对齐 `settings.systemPrompt` 并写入 managed shell wrapper（仍不碰 token / Base URL / MCP / 二进制）。

### 快速开始

先预览，不写入：

```bash
python3 claude-instruct.py install --scope project --project-dir /path/to/repo
```

确认后写入项目级规则：

```bash
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes
```

安装到用户级 `~/.claude/CLAUDE.md`：

```bash
python3 claude-instruct.py install --scope user --name personal-rules --yes
```

安装到本地项目偏好 `CLAUDE.local.md`：

```bash
python3 claude-instruct.py install \
  --scope local \
  --project-dir /path/to/repo \
  --name local-rules \
  --yes
```

使用自己的 Markdown 指令文件：

```bash
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --file ./my-claude-rules.md \
  --name team-rules \
  --yes
```


### runtime 注入（user scope，可选）

仅 import block **不够**。在当前 Claude Code（实测 `2.1.204` + lgw）上，硬性成人向创作还需要 CLI 层的 append：

```bash
python3 claude-instruct.py install --scope user --runtime --yes
python3 claude-instruct.py status --scope user --runtime
python3 claude-instruct.py doctor
```

`--runtime` 会额外写入：

| 路径 | 作用 |
|---|---|
| `~/.claude/keysmith/system-prompt.md` | 去 H1 后的 system 正文 |
| `~/.claude/keysmith/append-prompt.md` | 创意/成人向直接交付的 append 正文 |
| `~/.claude/settings.json` 的 `systemPrompt` | 与 system-prompt 对齐（**单独不够**） |
| `~/.zshrc` 中 managed `claude()` | 自动附加 `--system-prompt-file` + `--append-system-prompt-file` |

安全边界：

- 默认仍是 dry-run；必须 `--yes` 才写入
- 不改 Claude 二进制、MCP、网络、token
- 不把 Base URL / token 写入仓库或文档
- `settings.appendSystemPrompt` 在当前版本探测中**未生效**；真正有效的是 CLI append 参数
- 模型策略仍可能随机拒绝；`claude-opus-5` 优于 fable/sonnet；“续写/场景承接”比“冷开硬写”更稳

安装后：

```bash
source ~/.zshrc
claude   # 已自动带上 system + append
```

自定义 append 文本：

```bash
python3 claude-instruct.py install \
  --scope user \
  --runtime \
  --append-file ./my-append.md \
  --yes
```

### status

```bash
python3 claude-instruct.py status --scope project --project-dir /path/to/repo --name team-rules
```

JSON 输出：

```bash
python3 claude-instruct.py status --scope user --name personal-rules --json
```

### uninstall

默认只预览：

```bash
python3 claude-instruct.py uninstall --scope project --project-dir /path/to/repo --name team-rules
```

确认卸载：

```bash
python3 claude-instruct.py uninstall --scope project --project-dir /path/to/repo --name team-rules --yes
```

`uninstall` 不会清空整份 `CLAUDE.md`；它只删除：

```md
<!-- claude-keysmith:start name=team-rules -->
...
<!-- claude-keysmith:end name=team-rules -->
```

以及对应的 `.claude/keysmith/team-rules.md` 文件。

### restore

从指定备份恢复：

```bash
python3 claude-instruct.py restore \
  --target /path/to/repo/CLAUDE.md \
  --backup /path/to/repo/CLAUDE.md.bak_YYYYMMDD_HHMMSS \
  --yes
```

没有 `--yes` 时只预览，不写入。

### 验证

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

额外建议用临时 HOME / 临时 project directory 跑 user、project、local 三种 scope，确认不会触碰真实 Claude Code 配置。

### 项目结构

```text
claude-keysmith/
├── claude-instruct.py
├── examples/
│   └── claude-project-rules.md
├── tests/
│   └── test_claude_instruct.py
├── README.md
├── LICENSE
└── .gitignore
```

### 当前限制

- 目前是单文件 Python CLI，还没有打包成 `pip install` 工具。
- 只管理 `claude-keysmith` 自己插入的 HTML 注释区块。
- 不验证 Claude Code 是否实际加载了 import；需要在 Claude Code 内通过 `/memory` 或真机 smoke test 确认。
- 不管理 `.claude/rules/`、settings、hooks、permissions、MCP 或自动记忆目录。

---


### Runtime injection (optional, user scope)

Import blocks alone are not enough for hard creative/NSFW delivery on current Claude Code builds. Use:

```bash
python3 claude-instruct.py install --scope user --runtime --yes
python3 claude-instruct.py doctor
```

This writes `system-prompt.md`, `append-prompt.md`, aligns `settings.systemPrompt`, and installs a managed `claude()` shell wrapper that passes `--system-prompt-file` plus `--append-system-prompt-file`. It still does not patch binaries, store tokens, or guarantee provider-side policy bypass.

## English

### What is this?

`claude-keysmith` is a local helper for installing Markdown instruction files into Claude Code's official memory/import model. It writes a separate instruction file and inserts a small managed import block into `CLAUDE.md` or `CLAUDE.local.md`.

It is adapted from the safety posture of `codex-keysmith`, but it intentionally does not reuse Codex-specific logic such as `~/.codex/config.toml` or `model_instructions_file`.

### Supported scopes

| scope | Memory file | Instruction file | Import target |
|---|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `~/.claude/keysmith/<name>.md` | `@keysmith/<name>.md` |
| `project` | `<repo>/CLAUDE.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |
| `local` | `<repo>/CLAUDE.local.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |

### Commands

Preview install:

```bash
python3 claude-instruct.py install --scope project --project-dir /path/to/repo
```

Write after explicit confirmation:

```bash
python3 claude-instruct.py install --scope project --project-dir /path/to/repo --yes
```

Check status:

```bash
python3 claude-instruct.py status --scope project --project-dir /path/to/repo --name claude-project-rules
```

Uninstall only the matching managed block:

```bash
python3 claude-instruct.py uninstall --scope project --project-dir /path/to/repo --name claude-project-rules --yes
```

Restore from a selected backup:

```bash
python3 claude-instruct.py restore --target ./CLAUDE.md --backup ./CLAUDE.md.bak_YYYYMMDD_HHMMSS --yes
```

### Safety defaults

- Preview-only unless `--yes` is provided; if `--dry-run` and `--yes` are both provided, `--dry-run` wins.
- Backups before modifying existing memory files or instruction files.
- Safe filename validation for `--name`.
- Atomic writes.
- `uninstall` removes only the matching managed block.
- No binary patching, no network interception, no credential storage, no MCP changes, no running-process changes.

### Verification

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

### License

MIT
