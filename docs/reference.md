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

在 macOS / Linux 上，wrapper 是 `claude()` shell 函数；在 Windows PowerShell 上，wrapper 是 profile 中的 `function global:claude`。Windows 默认根据 `PSModulePath` 在 `Documents/WindowsPowerShell` 与 `Documents/PowerShell` 之间选择 profile，并检测 npm 全局安装的 `claude.cmd`。

可选环境变量覆盖：

| 变量 | 用途 |
|---|---|
| `CLAUDE_KEYSMITH_HOME` | 覆盖 home 目录解析 |
| `CLAUDE_KEYSMITH_SHELL` | 强制 `zsh` 或 `powershell` |
| `CLAUDE_KEYSMITH_SHELL_RC` | 强制 shell profile 路径 |
| `CLAUDE_KEYSMITH_CLAUDE_BIN` | 强制 Claude CLI 路径 |

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

## settings 字段

runtime install 保留 `settings.json` 中所有非目标字段，包括模型选择、环境变量、Base URL、认证配置与 MCP 配置。它会：

- 将顶层 `systemPrompt` 与 `system-prompt.md` 对齐；
- 只在传入 `--max-tokens` 时写入或更新顶层 `max_tokens`；
- 如已有 `env.CLAUDE_CODE_SYSTEM_PROMPT`，则将该镜像字段一起对齐；
- 删除已知无效的顶层 `appendSystemPrompt` 与 `appendSystemPromptFile`，避免让 status 误报它们是部署路径。

它不会创建 `env.CLAUDE_CODE_SYSTEM_PROMPT`，也不会写入、读取、打印或修改 token、cookie、Base URL、MCP 或 Claude Code 二进制。

## 备份、撤销与恢复

每次覆盖或修改已有文件前，工具会在同目录创建 timestamp 备份：

```text
<filename>.bak_YYYYMMDD_HHMMSS
<filename>.bak_YYYYMMDD_HHMMSS_pre_runtime
```

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

`runtime_ready` 表示 keysmith 的 system/append 文件和 managed shell wrapper 都存在；它不表示某个特定 CLI 会话、模型提供方或 API 网关一定会以预期方式处理请求。

## 限制

- 只支持 `user` scope 的 runtime；project/local scope 仅支持 import-block 层。
- runtime wrapper 支持 macOS / Linux 的 zsh 与 Windows 的 PowerShell。
- 工具不验证 Claude Code 是否在某个既有会话中重新读取指令。启动新会话并按实际任务 smoke test。
- 备份不会自动删除；在确认无需回滚后再手动清理。
