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
  <a href="docs/desktop-gui.md">桌面客户端 (beta)</a> ·
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

可选的 `--runtime` 会额外对齐 `settings.json` 的 `systemPrompt`，并安装 managed shell wrapper，使每次 shell 调用自动带上 `--system-prompt-file` 与 `--append-system-prompt-file`：macOS / Linux 使用 `~/.zshrc` 中的 `claude()`，Windows PowerShell 使用 profile 中的 `function global:claude`。

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

Windows PowerShell：

```powershell
python .\claude-instruct.py install --scope user --runtime       # 先预览
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py doctor --json
```

v6 正式支持 Windows PowerShell 5.1 和 PowerShell 7。managed wrapper 每次调用都会动态选择可用的 Claude Code 上游入口，不再把 npm 临时 shim 固化为唯一依赖；入口在更新期间暂时消失时，会等待最多 10 秒再给出 terminating error，且不会关闭当前 PowerShell。

Windows 可用以下可选环境变量覆盖自动检测：`CLAUDE_KEYSMITH_HOME`、`CLAUDE_KEYSMITH_SHELL`、`CLAUDE_KEYSMITH_SHELL_RC`、`CLAUDE_KEYSMITH_CLAUDE_BIN`。`CLAUDE_KEYSMITH_CLAUDE_BIN` 是严格入口覆盖；PowerShell profile 从实际用户级 `PSModulePath` 条目派生并支持重定向 Documents，即使其 `Modules` 目录尚未创建也会按路径结构识别；无法识别时必须用 `CLAUDE_KEYSMITH_SHELL_RC` 指定。

不要用 `curl | python` 直接执行；先下载或 clone 仓库、检查脚本与示例，再运行。

### 桌面客户端 (beta)

`gui/` 是本工具的桌面客户端：`0.1.0-beta.1`，channel `beta`，**未签名、未发布**。Tauri 2 + React 19，内嵌 PyInstaller sidecar（与 CLI 同源构建），提供 Dashboard / 三步部署向导 / Manage（卸载、受控备份恢复、recover）/ Settings 四页。

- 架构、进程边界与页面说明：[`docs/desktop-gui.md`](docs/desktop-gui.md)；工程规范：[`gui/SPEC.md`](gui/SPEC.md)。
- GUI 只消费 CLI 的 `--json` 契约（`claude-keysmith/v1`），所有写操作 preview → 确认 → `--yes`，恢复只用 `backups --json` 枚举的受控备份。
- 平台：macOS Apple Silicon 可构建 `.app` / `.dmg`；Windows x64 NSIS 已通过原生 CI 构建、静默安装/卸载和冻结 sidecar 自动化链，实体机可见 UI、SmartScreen 与无 WebView2 场景仍待验收；无 Linux GUI、无自动更新、无签名/公证。详见 [`docs/platform-support.md`](docs/platform-support.md) 与 [`docs/beta-acceptance.md`](docs/beta-acceptance.md)。

### CLI 自动化接口（v7 新增）

- 所有命令支持 `--json` 稳定输出：`install` / `status` / `doctor` / `uninstall` / `restore`，以及新增的只读 `backups`（枚举 keysmith 受控备份）与 `recover`（预览/执行中断事务恢复，幂等）。契约字段参考：[`docs/json-contract.md`](docs/json-contract.md)。
- 写操作现在由 scope 本地的 durable journal（`.journal-<uuid>.json`）+ 排他写锁（`.keysmith.lock`）保护：commit 前中断逆序回滚，commit 后永不反转，证据不足一律失败关闭。设计细节：[`docs/transaction-recovery.md`](docs/transaction-recovery.md)。
- v7 unix wrapper 修复：macOS / Linux 的 `claude()` wrapper 每次调用动态重解析 Claude 入口（保留已解析路径作为快路径，消失后经 `command -v claude` 重解析并带 zsh `disable -f`/`enable -f` 保护与 `command -v -p` 兜底，全部失败返回 127 并给出干净诊断），不再因 `command -v` 符号链接解析把版本目录烙进 wrapper 而在 Claude 更新后失效。
- `--max-tokens` 现在校验为正整数（argparse `type=positive_int`），0 / 负数 / 非数字给出干净的 usage error。

### 它会改哪些文件

| 路径 | 会发生什么 |
| --- | --- |
| `~/.claude/CLAUDE.md`、`<repo>/CLAUDE.md` 或 `<repo>/CLAUDE.local.md` | 插入或替换一个同名 managed import block；已有文件先备份 |
| 相邻的 `keysmith/<name>.md` 或 `.claude/keysmith/<name>.md` | 新建，或先备份再替换 |
| `~/.claude/keysmith/system-prompt.md`、`append-prompt.md` | 仅 `--runtime`：新建或备份后替换 |
| `~/.claude/settings.json` | 仅 `--runtime`：对齐顶层 `systemPrompt`；使用 `--max-tokens` 时才更新该字段；其余字段保留 |
| `~/.zshrc`（macOS / Linux）或 PowerShell profile（Windows） | 仅 `--runtime`：插入或替换一个带边界标记的 managed wrapper；已有文件先备份 |

Windows 升级时，工具还会预检旧的 `~/.local/bin/claude.ps1` / `claude.cmd`。只有能够确认是旧 keysmith wrapper 与同目录纯转发器时，才会在 `--yes` 下重命名为唯一 timestamp 备份；未知同名文件会阻止写入，不会被覆盖。

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
| 写操作中途崩溃或被 Ctrl+C 打断 | 运行 `recover --scope … --json` 预览残留与修复计划，确认后加 `--yes` 执行；重复执行幂等 |
| 需要找回被覆盖前的文件 | 运行 `backups --scope … --json` 列出受控备份，再用 `restore --target … --backup … --yes` 恢复 |
| import block 或文件状态异常 | 运行 `status --scope … --json`，确认目标路径、block 与指令文件 |
| Windows 更新后报 `required file is missing` | 使用当前版本重新运行 runtime install；先检查 dry-run 中的旧 launcher 迁移计划，再加 `--yes`，加载 profile 后运行 `status --json` 和 `doctor --json` |
| runtime 看起来没有生效 | macOS / Linux 先 `source ~/.zshrc`，Windows 先 `. $PROFILE`；然后运行 `doctor --json`，确认 prompt、settings、wrapper、上游入口和旧 launcher 状态 |
| 需要回滚 | 指定对应的 timestamp 备份运行 `restore`；恢复前工具会再为当前文件创建备份 |

Windows v5 runtime 升级示例：

```powershell
python .\claude-instruct.py install --scope user --runtime       # 查看 profile 与旧 launcher 迁移
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
```

`status --runtime --json` 保留已有字段，并提供 `upstream_candidates`、`upstream_path`、`upstream_exists`、`shell_wrapper_current`、`legacy_launcher_detected`、`legacy_launcher_paths`、`legacy_launcher_conflict`、`legacy_launcher_conflict_paths` 与 `upgrade_required`。`runtime_ready` 只有在 prompt 完整、settings 对齐、wrapper 为当前模板、存在可用上游入口，且没有未迁移或冲突的旧 launcher 时才为 `true`。

### 兼容性与限制

- 推荐 Python 3.8+；runtime wrapper 支持 macOS / Linux 的 zsh，以及 Windows PowerShell 5.1 / PowerShell 7。CMD 和 Git Bash 不属于正式 wrapper 支持范围。
- Windows 依次检测 strict override、native `~/.local/bin/claude.exe`、PATH 中非 npm prefix 的 WinGet/native exe、npm 包内 `bin/claude.exe` 与 npm shim 兜底；旧 `.local/bin/claude.ps1/.cmd` 以不可选候选记录并排除。
- 只管理 `claude-keysmith` 自己插入的 HTML 注释 block，不覆盖用户其余 memory 内容。
- 不管理 Claude Code 二进制、运行中进程、网络、MCP、token、cookie、Base URL、hooks 或 permissions。
- 安装 Agent 不得自行创建或替换 `~/.local/bin/claude.ps1`、`~/.local/bin/claude.cmd`；这些 launcher 由 Claude Code 上游安装器管理。
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
