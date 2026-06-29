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
> `claude-keysmith` is a small local helper for managing Claude Code `CLAUDE.md` import blocks and separate Markdown instruction files. It is not a Claude Code fork, does not patch binaries, does not intercept network traffic, does not save credentials, tokens, cookies, or MCP secrets, and does not guarantee that installed instructions will improve model behavior.
>
> `claude-keysmith` 是一个小型本地工具，用来管理 Claude Code `CLAUDE.md` 中的 import 区块，以及独立存放的 Markdown 指令文件。它不是 Claude Code 分叉版，不修改二进制，不劫持网络，不保存凭证、token、cookie 或 MCP 机密，也不保证安装后的指令一定改善模型行为。

## 复制给智能体安装

把下面这段话复制到 Codex、Claude Code、Cursor Agent 或其他智能体：

```text
请使用 https://github.com/Jia-Ethan/claude-keysmith 帮我安全安装 Claude Code 的 user scope 本地 CLAUDE.md import-block 指令文件，也就是写入 ~/.claude/CLAUDE.md 和 ~/.claude/keysmith/<name>.md。先阅读 README 和脚本，默认只做静态审计和 dry-run，不要直接写入；写入前展示将修改的准确文件路径、备份路径和 import block，并等我确认；确认后先备份再安装。不要修改 Claude Code 二进制、settings、MCP、网络、运行进程，也不要保存任何 token、cookie 或私密配置。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

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
- 不修改 `~/.claude/settings.json`、`.claude/settings.json`、MCP、凭证、二进制或运行中进程。

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
