<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude-Code-555555">
</p>

<h1 align="center">claude-keysmith</h1>

<p align="center">
  Managed import-block installer for Claude Code local instruction files, with an optional user-scope runtime wrapper for persistent system+append prompt injection.
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装 / Agent install</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="Head version v4.0" src="https://img.shields.io/badge/prompt-v4.0-0099CC">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

> **Status boundary / 状态边界**
>
> `claude-keysmith` is a small local helper for managing Claude Code `CLAUDE.md` import blocks, separate Markdown instruction files, and an optional user-scope runtime wrapper. It is not a Claude Code fork, does not patch binaries, does not intercept network traffic, does not save credentials, tokens, cookies, or MCP secrets, and does not guarantee that installed instructions will unlock every model behavior on every provider.
>
> `claude-keysmith` 是一个小型本地工具，用来管理 Claude Code `CLAUDE.md` 中的 import 区块、独立 Markdown 指令文件，以及可选的 user-scope runtime 包装层。它不是 Claude Code 分叉版，不修改二进制，不劫持网络，不保存凭证、token、cookie 或 MCP 机密，也不保证安装后在每个供应商/模型上都能突破全部内容策略。

## 简体中文

### 这是什么

`claude-keysmith` 是 `codex-keysmith` 思路的 Claude Code 版实现。`codex-keysmith` 围绕 Codex CLI 的 `model_instructions_file` 与 `~/.codex/config.toml` 做版本化指令部署；`claude-keysmith` 复用了同样的安全姿态——dry-run 优先、显式确认才写入、备份回滚、分层卸载——但面向的目标完全不同：

- **import-block 层**：将指令 Markdown 写入 keysmith 管理目录，在 `CLAUDE.md` / `CLAUDE.local.md` 中插入可识别、可卸载的 import 注释块；
- **runtime 层（可选）**：对齐 `settings.systemPrompt` 并安装 managed shell wrapper，使每个 `claude` 调用自动注入 `--system-prompt-file` + `--append-system-prompt-file`。

**这会改变 Claude Code 的全局行为，不是项目级设置**：import block 影响所有加载该 `CLAUDE.md` 的会话；runtime 层影响通过 shell wrapper 启动的每个会话。内置示例提示词会调整模型的角色、输出格式、技术文档与创作响应风格。**这不是安全边界，是一次行为切换**——用前打开 [`examples/claude-project-rules.md`](examples/claude-project-rules.md) 和 [`examples/claude-append-prompt.md`](examples/claude-append-prompt.md) 看一眼，或通过 `--file` / `--append-file` 换成你自己的指令。Claude Code、模型提供方和 API 网关仍可能应用自己的策略；本工具不承诺覆盖这些策略。

> [!WARNING]
> `--runtime` 会修改 user-scope 的 `~/.claude/settings.json` 与 `~/.zshrc`，并影响经 managed `claude()` wrapper 启动的后续会话；它不是项目级配置。先 dry-run，确认路径、示例内容和 shell wrapper 后再加 `--yes`。

### 复制给智能体安装

把下面这段复制给 Codex、Claude Code、Cursor Agent 或其他能读取本地仓库的智能体：

```text
请使用 https://github.com/Jia-Ethan/claude-keysmith 帮我安装 Claude Code 的本地指令文件。先阅读 README、claude-instruct.py 和 examples；默认只执行 dry-run，不要直接写入。展示将修改的精确路径、备份路径和 managed import block，等我确认后才加 --yes。若我明确要求 --runtime，额外说明将修改 ~/.claude/settings.json 的 systemPrompt（以及可选 max_tokens）和 ~/.zshrc 的 managed claude() wrapper；不要修改 Claude Code 二进制、MCP、网络、token、cookie、Base URL 或运行中进程，也不要输出或保存任何凭证。
```

### 快速开始

默认 dry-run，先看再信：

```bash
# 项目级 import block
python3 claude-instruct.py install --scope project --project-dir /path/to/repo

# user-scope runtime（对齐 settings + shell wrapper）
python3 claude-instruct.py install --scope user --runtime
```

确认后写入：

```bash
# 项目级
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes

# user-scope runtime
python3 claude-instruct.py install --scope user --runtime --yes
```

不要用 `curl | python` 直接执行——先落盘确认内容，再运行。

### 支持范围

| scope | 被修改的 memory 文件 | 指令文件位置 | import 目标 |
|---|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `~/.claude/keysmith/<name>.md` | `@keysmith/<name>.md` |
| `project` | `<repo>/CLAUDE.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |
| `local` | `<repo>/CLAUDE.local.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |

Managed block 示例：

```md
<!-- claude-keysmith:start name=claude-project-rules -->
@.claude/keysmith/claude-project-rules.md
<!-- claude-keysmith:end name=claude-project-rules -->
```

### 它会改哪些文件

基础 install 只拥有同名 managed block 与对应 keysmith 指令文件：

| 路径 | 会发生什么 |
|---|---|
| `~/.claude/CLAUDE.md`、`<repo>/CLAUDE.md` 或 `<repo>/CLAUDE.local.md` | 新增或替换一个同名 import 注释块；已有文件先备份 |
| 相邻的 `keysmith/<name>.md` 或 `.claude/keysmith/<name>.md` | 新建，或先备份再替换 |
| 上述文件的 `.bak_<timestamp>` 副本 | 写入前自动生成；工具不会自动清理 |

启用 `--runtime` 时，额外处理：

| 路径 | 会发生什么 |
|---|---|
| `~/.claude/keysmith/system-prompt.md` | 写入去 H1 后的 system 正文；已有文件先备份 |
| `~/.claude/keysmith/append-prompt.md` | 写入 append 正文；已有文件先备份 |
| `~/.claude/settings.json` | 对齐 `systemPrompt`；只有显式传入 `--max-tokens` 才写入该字段；保留 token、Base URL、模型和 MCP 等其余现有字段 |
| `~/.zshrc` | 新增或替换一个 `claude-keysmith` managed `claude()` wrapper；已有文件先备份 |

完整 runtime 状态可用 `python3 claude-instruct.py doctor --json` 检查；字段所有权、settings 更新和恢复语义见 [`docs/reference.md`](docs/reference.md)。

### runtime 层（user scope，可选）

仅 import block 不能覆盖所有 Claude Code 启动路径。需要为每个 shell 调用稳定传入自定义 system/append 指令时，可启用 CLI 层的 runtime wrapper：

```bash
python3 claude-instruct.py install --scope user --runtime --yes
python3 claude-instruct.py doctor
```

`--runtime` 会额外写入：

| 路径 | 作用 |
|---|---|
| `~/.claude/keysmith/system-prompt.md` | 去 H1 后的 system 正文 |
| `~/.claude/keysmith/append-prompt.md` | 创意/成人向直接交付的 append 正文 |
| `~/.claude/settings.json` 的 `systemPrompt` | 与 system-prompt 对齐（**单独不够**；真正有效的是 CLI append） |
| `~/.zshrc` 中 managed `claude()` wrapper | 自动附加 `--system-prompt-file` + `--append-system-prompt-file` |

安全边界：

- 默认 dry-run；必须 `--yes` 才写入
- 不改 Claude 二进制、MCP、网络、token
- 不把 Base URL / token 写入仓库或文档
- `settings.appendSystemPrompt` / `appendSystemPromptFile` 不作为部署路径；wrapper 明确传入 CLI 文件参数
- Claude Code、模型提供方和 API 网关仍可按各自策略处理请求

安装后：

```bash
source ~/.zshrc
claude   # 已自动带上 system + append
```

自定义 append：

```bash
python3 claude-instruct.py install \
  --scope user \
  --runtime \
  --append-file ./my-append.md \
  --max-tokens 32000 \
  --yes
```

### 命令参考

**install** — 安装或更新 managed import block、keysmith 指令文件，可选 runtime 注入

| 参数 | 作用 |
|---|---|
| `--scope user/project/local` | 安装范围 |
| `--name` | 指令文件名（不含 `.md`，默认 `claude-project-rules`） |
| `--file` | 外部 Markdown 指令文件；不传用内置示例 |
| `--runtime` | user scope 额外注入 system/append prompt + shell wrapper |
| `--append-file` | runtime append 指令文件 |
| `--max-tokens` | 同时设置 `settings.json` 的 `max_tokens` |
| `--yes` | 确认写入；未提供时只预览 |

**status** — 检查 managed block 与指令文件是否存在

```bash
python3 claude-instruct.py status --scope user --name personal-rules
python3 claude-instruct.py status --scope user --runtime --json
```

**uninstall** — 只移除同名 managed block 和对应 keysmith 指令文件；不自动清空 systemPrompt

```bash
python3 claude-instruct.py uninstall --scope user --runtime --yes
```

**restore** — 从指定备份恢复

```bash
python3 claude-instruct.py restore \
  --target ./CLAUDE.md \
  --backup ./CLAUDE.md.bak_YYYYMMDD_HHMMSS \
  --yes
```

**doctor** — 检查当前机器上 system/append prompt、settings 对齐和 managed shell wrapper 的有效状态

```bash
python3 claude-instruct.py doctor --json
```

### 撤销

默认仍是预览；先确认会移除的 managed block 和文件：

```bash
# 只撤销项目级 import block 与对应指令文件
python3 claude-instruct.py uninstall \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules

# 撤销 user-scope runtime 文件与 wrapper
python3 claude-instruct.py uninstall --scope user --runtime
```

确认后再加 `--yes`：

```bash
python3 claude-instruct.py uninstall --scope user --runtime --yes
```

`uninstall --runtime` 会移除 keysmith 管理的 system/append prompt 与 shell wrapper，但**不会自动清空** `settings.json` 中的 `systemPrompt`；需要恢复时，用安装前生成的 `settings.json.bak_<timestamp>_pre_runtime` 通过 `restore` 明确回滚。

### 出问题了怎么办

| 现象 | 应该做的事 |
|---|---|
| import block 状态不对 | `--status` 先看 JSON 输出，确认 block / 文件是否存在 |
| 安装完后 Claude Code 行为没变 | runtime 没开？`doctor` 检查 shell wrapper 是否在 `~/.zshrc`、`system/append-prompt.md` 是否存、settings 是否对齐 |
| 想回滚 | 先用 `restore --target` 从指定 timestamp 备份恢复；`uninstall --runtime` 不会自动恢复 settings 的旧 `systemPrompt` |
| 想彻底清掉 | `uninstall --scope user --runtime --yes`，再决定是否用 `restore` 回滚 `settings.json`，最后手动清理确认无用的备份 |

备份由工具自动生成（timestamp 命名），但不会自动清理；你需要时手动删旧备份。

### 兼容性与限制

- 推荐 Python 3.8+；runtime 层目前依赖 `zsh` 与 `~/.zshrc`
- 不打包为 `pip install`，不自动更新
- 只管理 `claude-keysmith` 自己插入的 HTML 注释区块，不覆盖整份用户文件
- 不验证 Claude Code 是否实际加载了 import；需要在 Claude Code 内通过 `/memory` 或真机 smoke test 确认
- 不管理 `.claude/rules/`、settings（除 runtime 的 systemPrompt 对齐）、hooks、permissions、MCP 或自动记忆目录

### 验证

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

建议额外用临时 `HOME` / 临时 `project` 目录跑三种 scope，确认不碰真实配置。

### 项目结构

```text
claude-keysmith/
├── claude-instruct.py
├── examples/
│   ├── claude-project-rules.md     ← v4.0 system prompt 默认
│   └── claude-append-prompt.md     ← runtime append 默认
├── tests/
│   └── test_claude_instruct.py
├── docs/
│   ├── agent-install.md            ← 智能体安装流程
│   └── reference.md                ← 文件所有权与恢复参考
├── README.md
├── LICENSE
└── .gitignore
```

### 参与贡献

提交前确保 `python3 -m pytest tests` 全部通过。

### 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — Codex CLI 版本化指令部署，支持预览、hook 隔离、中断恢复与分层卸载。 / Versioned instruction deployment for local Codex CLI configuration with preview, hook isolation, interruption recovery, and layered uninstall.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — Claude Code `CLAUDE.md` 的受管理 import-block 安装器，用于本地 Markdown 指令文件。 / Managed Claude Code `CLAUDE.md` import-block installer for local Markdown instruction files.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — Grok Build `AGENTS.md` 安装器，支持 compat/hook 隔离、中断恢复与分层卸载。 / Global `AGENTS.md` installation for Grok Build with compat/hook isolation, interruption recovery, and layered uninstall.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — ZCode App 的受管理 true system-role 入口，通过 agent-server wrapper 将 `system-role.md` 接入 runtime `customSystemPrompt` 的 system-message 路径。 / Managed true system-role entrypoint for ZCode App; an agent-server wrapper routes `system-role.md` into the runtime `customSystemPrompt` system-message path.
- [role-keysmith](https://github.com/Jia-Ethan/role-keysmith) — Codex skill source，根据目标岗位 JD 定制中文简历。 / Codex skill source for JD-matched Chinese resume rewriting.

---

## English

### What is this?

`claude-keysmith` is the Claude Code realization of the `codex-keysmith` approach. `codex-keysmith` does versioned instruction deployment via Codex CLI's `model_instructions_file` and `~/.codex/config.toml`; `claude-keysmith` keeps the same safety posture — dry-run first, explicit confirmation, backup and rollback, layered uninstall — but targets a different surface:

- **import-block layer**: stores instruction Markdown in a keysmith-managed directory and anchors it into `CLAUDE.md` / `CLAUDE.local.md` with a recognizable, uninstallable import comment block;
- **runtime layer (optional)**: aligns `settings.systemPrompt` and installs a managed `claude()` shell wrapper that passes `--system-prompt-file` + `--append-system-prompt-file` on every invocation.

### Supported scopes

| scope | Memory file | Instruction file | Import target |
|---|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `~/.claude/keysmith/<name>.md` | `@keysmith/<name>.md` |
| `project` | `<repo>/CLAUDE.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |
| `local` | `<repo>/CLAUDE.local.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |

### Quick start

```bash
# Preview only (default)
python3 claude-instruct.py install --scope project --project-dir /path/to/repo

# Write after confirmation
python3 claude-instruct.py install --scope project --project-dir /path/to/repo --yes

# User-scope runtime (system+append prompt + shell wrapper)
python3 claude-instruct.py install --scope user --runtime --yes
```

### Runtime layer (user scope, optional)

Import blocks alone cannot cover every Claude Code launch path. Enable the runtime wrapper when each shell invocation must receive the same custom system and append instructions:

```bash
python3 claude-instruct.py install --scope user --runtime --yes
python3 claude-instruct.py doctor
```

This writes `system-prompt.md`, `append-prompt.md`, aligns `settings.systemPrompt`, and installs a managed `claude()` shell wrapper. It does not promise to override Claude Code, model-provider, or API-gateway policies. After install: `source ~/.zshrc`.

### Commands

| Command | Purpose |
|---|---|
| `install --scope` | Insert managed import block + write instruction file; `--runtime` adds system/append + shell wrapper |
| `status --scope` | Check block / file existence; `--json` for programmatic consumption |
| `uninstall --scope` | Remove own block and instruction file; `--runtime` also removes prompts + shell wrapper |
| `restore --target --backup` | Restore target from a timestamped backup |
| `doctor` | Inspect effective system/append prompt, settings, and shell-wrapper state |

### Safety defaults

- Preview-only unless `--yes`; if `--dry-run` and `--yes` both given, `--dry-run` wins
- Backups before modification
- Safe filename validation for `--name` (letters, digits, dots, hyphens, underscores; no paths)
- Atomic writes
- `uninstall` removes only the matching managed block
- No binary patching, no network interception, no credential storage
- Does not promise to override Claude Code, model-provider, or API-gateway policies

### Verification

```bash
python3 -m py_compile claude-instruct.py
python3 -m pytest tests
```

### Reference

- [Runtime reference](docs/reference.md): file ownership, settings fields, backup, uninstall, and restore semantics
- [Agent install](docs/agent-install.md): auditable preview-first installation workflow

### License

MIT
