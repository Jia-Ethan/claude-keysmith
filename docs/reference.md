# claude-keysmith 运行时参考

`claude-keysmith` 管理 Claude Code 的两层持久化指令入口：import block 与可选 user-scope runtime wrapper。所有写入默认需要显式 `--yes`；没有 `--yes` 时命令只预览。

## import-block 层

| Scope | memory 文件 | 指令文件 | import 目标 |
|---|---|---|---|
| `user` | `~/.claude/CLAUDE.md` | `~/.claude/keysmith/<name>.md` | `@keysmith/<name>.md` |
| `project` | `<repo>/CLAUDE.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |
| `local` | `<repo>/CLAUDE.local.md` | `<repo>/.claude/keysmith/<name>.md` | `@.claude/keysmith/<name>.md` |

工具只拥有如下形状、且 `name` 完全匹配的 managed block：

```md
<!-- claude-keysmith:start name=NAME -->
@IMPORT_TARGET
<!-- claude-keysmith:end name=NAME -->
```

`install` 会插入或替换同名 block；不会覆盖其余 `CLAUDE.md` 内容。`uninstall` 也只会移除同名 block 与对应指令文件。

## runtime 层

只有 `install --scope user --runtime` 会处理 runtime 层：

| 文件 | 所有权与处理方式 |
|---|---|
| `~/.claude/keysmith/system-prompt.md` | keysmith 管理；写入前备份，写入 source prompt 去掉首个 Markdown H1 后的正文 |
| `~/.claude/keysmith/append-prompt.md` | keysmith 管理；写入前备份，内容来自 `--append-file` 或内置示例 |
| `~/.claude/settings.json` | 只对齐顶层 `systemPrompt`；仅在显式使用 `--max-tokens N` 时写入顶层 `max_tokens`；保留其他 JSON 字段 |
| `~/.zshrc`（macOS / Linux）或 PowerShell profile（Windows） | 只管理 `# >>> claude-keysmith runtime >>>` 与结束标记之间的 wrapper；写入前备份 |

在 macOS / Linux 上，wrapper 是 `claude()` shell 函数；在 Windows PowerShell 上，wrapper 是 profile 中的 `function global:claude`。v6 正式支持 Windows PowerShell 5.1 与 PowerShell 7；CMD 和 Git Bash 不属于 managed wrapper 支持范围。

Windows profile 解析从实际用户级 `PSModulePath` 的首个可识别条目派生：条目中的 `WindowsPowerShell/Modules` 对应 Windows PowerShell 5.1 profile，`PowerShell/Modules` 对应 PowerShell 7 profile，并保留该条目前缀，因此支持重定向后的 Documents 目录。全新环境中，即使 `PSModulePath` 已声明的用户 `Modules` 目录尚未创建，也会按路径结构识别；没有可识别条目时，安装会停止并要求通过 `CLAUDE_KEYSMITH_SHELL_RC` 指定目标 profile，不会回退猜测。

可选环境变量覆盖：

| 变量 | 用途 |
|---|---|
| `CLAUDE_KEYSMITH_HOME` | 覆盖 home 目录解析 |
| `CLAUDE_KEYSMITH_SHELL` | 强制 `zsh` 或 `powershell` |
| `CLAUDE_KEYSMITH_SHELL_RC` | 强制 shell profile 路径 |
| `CLAUDE_KEYSMITH_CLAUDE_BIN` | 严格指定 Claude CLI 上游入口；路径无效时不回退到自动候选 |

生成的 macOS / Linux shell wrapper 等价于：

```zsh
claude() {
  "$HOME/.local/bin/claude" \
    --system-prompt-file "$HOME/.claude/keysmith/system-prompt.md" \
    --append-system-prompt-file "$HOME/.claude/keysmith/append-prompt.md" \
    "$@"
}
```

路径在真实 wrapper 中会被解析为绝对路径。启用后新 shell 需要 `source ~/.zshrc` 或重新打开终端。Windows PowerShell 需要 `. $PROFILE` 或重新打开 PowerShell。

### Windows 上游入口解析

PowerShell wrapper 不把安装时发现的 npm shim 固化为唯一依赖。每次执行 `claude` 时，它按以下顺序动态检查候选：

1. `CLAUDE_KEYSMITH_CLAUDE_BIN` 显式 override；
2. native `~/.local/bin/claude.exe`；
3. PATH 中非 npm prefix 的 WinGet/native `.exe`；
4. npm 包目录中的 `bin/claude.exe`，包括默认和自定义 npm prefix；
5. npm `claude.cmd` / `claude.ps1` / `claude.exe` shim 兜底。

`CLAUDE_KEYSMITH_CLAUDE_BIN` 是 strict override：一旦设置，路径无效时也不回退。npm prefix 来自 `NPM_CONFIG_PREFIX`、`APPDATA/npm` 和 PATH 中可识别的 npm 布局。`~/.local/bin/claude.ps1/.cmd` 会以 `eligible: false` 记录并排除，避免递归。若全部候选在 Claude Code 自更新期间暂时消失，wrapper 每 250 ms 重新检测一次，最多等待 10 秒。找到入口后只启动一次；启动后没有自动重试路径，因此非零退出或中断不会触发第二次执行。真实 Ctrl+C 行为仍需人工补验，不能用退出码 130 模拟替代。

wrapper 始终传入 `--system-prompt-file`、`--append-system-prompt-file` 和原始 `@args`，并保留上游退出码。入口在等待窗口结束后仍不可用时，它抛出 terminating error；不会使用 `exit` 关闭当前 PowerShell 会话。

### 旧 Windows launcher 迁移

v5 或更早的安装 Agent 可能在 `~/.local/bin` 创建 `claude.ps1` 与 `claude.cmd`，抢占上游入口或引用更新期间消失的 npm shim。`install --scope user --runtime` 会在任何 runtime 写入前预检这两个路径：

- `.ps1` 必须包含可识别的 keysmith/prompt 标记；
- `.cmd` 必须只是转发到同目录 `claude.ps1` 的 launcher；
- 两者满足所有权规则时，dry-run 展示迁移计划，`--yes` 才将它们重命名为 `.bak_TIMESTAMP_pre_v6[_N]` 唯一备份；
- 任何未知同名文件都会报告冲突，保持原样，并阻止本次 runtime 写入。

安装 Agent 不得自行创建或替换 `~/.local/bin/claude.ps1`、`~/.local/bin/claude.cmd`。keysmith 只在 PowerShell profile 中管理自己的有界 function；Claude Code 可执行文件及 launcher 由上游安装器管理。

## settings 字段

runtime install 保留 `settings.json` 中所有非目标字段，包括模型选择、环境变量、Base URL、认证配置与 MCP 配置。它会：

- 将顶层 `systemPrompt` 与 `system-prompt.md` 对齐；
- 只在传入 `--max-tokens` 时写入或更新顶层 `max_tokens`；
- 如已有 `env.CLAUDE_CODE_SYSTEM_PROMPT`，则将该镜像字段一起对齐；
- 删除已知无效的顶层 `appendSystemPrompt` 与 `appendSystemPromptFile`，避免让 status 误报它们是部署路径。

它不会创建 `env.CLAUDE_CODE_SYSTEM_PROMPT`，也不会写入或修改 token、cookie、Base URL、MCP 或 Claude Code 二进制。`doctor` 的文本、stderr 与 JSON 输出不包含 Base URL 或潜在凭证。

## 备份、撤销与恢复

每次覆盖或修改已有文件前，工具会在同目录创建 timestamp 备份：

```text
<filename>.bak_YYYYMMDD_HHMMSS
<filename>.bak_YYYYMMDD_HHMMSS_pre_runtime
```

同一秒内重复备份时会生成唯一文件名，不覆盖已有恢复点。原子写入失败时，工具会清理自己创建的临时文件，并保留原 target。

旧 Windows launcher 的迁移备份也保留在原目录。需要回滚 launcher 时，先确认 PowerShell profile 中的 managed wrapper 已卸载或不再加载，再将选定备份显式重命名回原文件；不要同时恢复多个 timestamp 版本。

`uninstall --runtime` 会移除 keysmith 管理的 `system-prompt.md`、`append-prompt.md` 和 managed shell wrapper；它**不会**自动清空或恢复 `settings.json` 的 `systemPrompt`。这是为了避免覆盖安装后由用户或其他工具写入的 settings 变动。

如需恢复旧 settings，显式指定安装前备份：

```bash
python3 claude-instruct.py restore \
  --target ~/.claude/settings.json \
  --backup ~/.claude/settings.json.bak_YYYYMMDD_HHMMSS_pre_runtime \
  --yes
```

恢复会先为当前 target 创建新的 `pre_restore` 安全备份。

## 状态与排障

```bash
# import block 及指令文件
python3 claude-instruct.py status --scope user --name claude-project-rules --json

# runtime 文件、settings 对齐、wrapper 是否存在
python3 claude-instruct.py status --scope user --runtime --json

# 更完整的运行时诊断
python3 claude-instruct.py doctor --json
```

runtime status 保留已有字段，并增加：

| 字段 | 含义 |
|---|---|
| `upstream_candidates` | Windows 动态解析候选；每项包含 `kind`、`path`、`exists`、`eligible`、`reason` |
| `upstream_path` | 当前选中的上游入口；没有可用入口时为空 |
| `upstream_exists` | 当前是否至少有一个可启动的上游入口 |
| `shell_wrapper_current` | profile 中的 managed wrapper 是否匹配 v6 当前模板 |
| `legacy_launcher_detected` | 是否发现尚未迁移的旧 Windows launcher |
| `legacy_launcher_paths` | 发现的旧 launcher 路径列表 |
| `legacy_launcher_conflict` | 是否发现所有权无法确认的同名 Windows launcher |
| `legacy_launcher_conflict_paths` | 发生所有权冲突的 launcher 路径列表 |
| `upgrade_required` | 当前 runtime 是否需要重新安装或迁移 |

`runtime_ready` 只有在 system/append prompt 文件完整、settings 对齐、managed wrapper 匹配 v6 当前模板、至少一个上游入口存在，并且没有未迁移或冲突的旧 launcher 时才为 `true`。它不表示某个特定 CLI 会话、模型提供方或 API 网关一定会以预期方式处理请求。

`doctor` 仅报告安装类型、相关路径、上游候选拒绝原因和建议的修复动作。它不会在文本、stderr 或 JSON 中回显 Base URL、token、cookie 等潜在凭证。

## 限制

- 只支持 `user` scope 的 runtime；project/local scope 仅支持 import-block 层。
- runtime wrapper 支持 macOS / Linux 的 zsh 与 Windows PowerShell 5.1 / PowerShell 7；不承诺支持 CMD 或 Git Bash wrapper。
- 上游安装器仍可能改变 Claude Code 的安装布局；出现 `upgrade_required` 或入口不可用时，先 dry-run 检查，再重新安装 runtime 并做真实 smoke test。
- 工具不验证 Claude Code 是否在某个既有会话中重新读取指令。启动新会话并按实际任务 smoke test。
- 备份不会自动删除；在确认无需回滚后再手动清理。
