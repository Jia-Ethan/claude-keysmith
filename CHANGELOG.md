# Changelog

## v6 (Unreleased)

### Windows updater resilience

修复 Windows runtime wrapper 将 npm 的 `claude.ps1` shim 固化为唯一入口后，Claude Code 更新期间或安装方式变化时出现 `required file is missing` 的问题。

**上游入口解析：**

- PowerShell wrapper 不再依赖安装时捕获的单一 npm shim，而是在每次调用时动态选择可用的 Claude Code 入口。
- Windows 候选顺序为：strict `CLAUDE_KEYSMITH_CLAUDE_BIN` 覆盖、`~/.local/bin/claude.exe`、PATH 中非 npm prefix 的 WinGet/native `.exe`、npm 包内 `bin/claude.exe`、npm `claude.cmd` / `claude.ps1` / `claude.exe` shim 兜底。
- 候选解析会排除 claude-keysmith 自己管理或遗留的包装器，避免递归调用。
- 所有候选暂时缺失时，每 250 ms 重新检测一次，最多等待 10 秒；上游进程一旦启动，不因非零退出或中断而自动重试，避免重复执行命令。
- wrapper 继续注入 system/append 两个 prompt 文件、完整透传参数并保留上游退出码；失败使用 terminating error，不关闭当前 PowerShell 会话。

**Windows 升级与兼容：**

- `install --scope user --runtime` 会在写入前检查 `~/.local/bin/claude.ps1` 和 `claude.cmd`。
- 只有确认属于旧 keysmith/prompt wrapper 的 `.ps1`，以及仅转发到同目录 `.ps1` 的 `.cmd`，才会在 `--yes` 下重命名为唯一 timestamp 备份。
- 无法确认所有权的同名 launcher 会在 dry-run 和写入模式中报告冲突；工具不会修改它，也不会执行其他 runtime 写入。
- PowerShell profile 从实际用户级 `PSModulePath` 的首个可识别条目派生，支持重定向后的 Documents 目录和尚未创建的已声明用户 `Modules` 目录；无法识别时要求显式设置 `CLAUDE_KEYSMITH_SHELL_RC`。
- 正式支持范围为 Windows PowerShell 5.1 与 PowerShell 7；CMD 和 Git Bash 不属于 v6 managed wrapper 支持范围。

**状态、诊断与文件安全：**

- 新增 `--version`，输出 `claude-keysmith v6`。
- runtime status 新增 `upstream_candidates`、`upstream_path`、`upstream_exists`、`shell_wrapper_current`、`legacy_launcher_detected`、`legacy_launcher_paths`、`upgrade_required`，同时保留已有字段。
- `runtime_ready` 现在要求 prompt 文件完整、settings 对齐、wrapper 为 v6 当前模板、至少一个上游入口存在，并且没有未迁移的旧 launcher。
- `doctor` 不再输出 Base URL 或潜在凭证，只报告安装类型、路径、候选拒绝原因与修复动作。
- 同一秒内的备份使用唯一文件名，不覆盖既有恢复点；原子写入失败时清理临时文件。

**升级：**

```powershell
python .\claude-instruct.py install --scope user --runtime       # 先预览迁移与写入
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
python .\claude-instruct.py doctor --json
```

安装 Agent 不得自行创建或替换 `~/.local/bin/claude.ps1`、`~/.local/bin/claude.cmd`；Claude Code 二进制及其 launcher 由上游安装器管理。

**发布前门禁：**

- 最终整合 diff 已完成本地 `py_compile`、Python 3.9/3.14 全量 pytest 与文档一致性检查。
- GitHub Actions 已配置 Ubuntu、macOS、Windows 及 Python 3.8/3.14 矩阵，发布前仍须等待实际运行通过。
- Windows runner 已配置分别使用 Windows PowerShell 5.1 与 PowerShell 7 加载并执行生成的 wrapper；真实 Ctrl+C 另列人工门禁。
- 在事故机或等价 Windows 环境真实复测 `claude update`，并保留旧 launcher 迁移与回滚证据。

## v5 (2026-07-29)

### Windows / PowerShell 运行时支持

添加完整的 Windows 环境下 `--runtime` 支持，以及跨平台的 shell 自动检测。

**新增函数：**

| 函数 | 用途 |
|---|---|
| `resolve_home()` | `$CLAUDE_KEYSMITH_HOME` → `$HOME` → `Path.home()` 三级优先解析；修复 Windows 上 `Path.home()` 忽略 `$HOME` 的问题 |
| `runtime_shell_kind()` | `os.name == "nt"` 返回 `"powershell"`，否则 `"zsh"`；可通过 `$CLAUDE_KEYSMITH_SHELL` 覆盖 |
| `powershell_profile_path()` | 根据 `PSModulePath` 区分 PS5（`WindowsPowerShell`）vs PS7（`PowerShell`）的 profile 路径；可通过 `$CLAUDE_KEYSMITH_SHELL_RC` 覆盖 |
| `find_claude_binary()` | 依次查找 `claude.cmd` / `claude.exe` / `claude`，fallback 到 `%APPDATA%/npm/claude.cmd`；可通过 `$CLAUDE_KEYSMITH_CLAUDE_BIN` 覆盖 |
| `_powershell_quote()` | PowerShell 单引号转义，`' → ''` |

**修改函数：**

- `render_shell_wrapper()` — 新增 `shell_kind` 参数；`shell_kind == "powershell"` 时生成 `function global:claude { … @args }`，否则生成 `claude() { … "$@" }`
- `user_runtime_paths()` — 返回类型 `Dict[str, Path]` → `Dict[str, Any]`；新增 `shell_kind` 和 `shell_rc` 字段；`"zshrc"` 键保留为 `shell_rc` 的别名
- `resolve_scope()` — user scope 使用 `resolve_home()` 替代 `Path.home()`
- 所有 install / uninstall / status / doctor 命令 — 固定 `zshrc` 引用改为 `shell_rc`，并输出 `shell_kind`；reload 提示根据平台给出 `source ~/.zshrc` 或 `. $PROFILE`

**新增环境变量：**

| 变量 | 默认值 | 用途 |
|---|---|---|
| `CLAUDE_KEYSMITH_HOME` | `$HOME` → `Path.home()` | 覆盖 home 目录解析 |
| `CLAUDE_KEYSMITH_SHELL` | `nt` → `powershell`，否则 `zsh` | 强制 shell 类型 |
| `CLAUDE_KEYSMITH_SHELL_RC` | 自动推断 | 强制 shell profile 路径 |
| `CLAUDE_KEYSMITH_CLAUDE_BIN` | 自动检测 | 强制 claude 二进制路径 |

**向后兼容：**

- macOS / Linux 行为完全不变
- 所有 `CLAUDE_KEYSMITH_*` 环境变量可选，自动检测开箱即用

**Windows 安装示例：**

```powershell
python .\claude-instruct.py install --scope user --runtime       # 预览
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py doctor --json
```

**文档更新：**

- README.md / README.en.md — 新增 Windows PowerShell 快速开始节、环境变量说明、兼容性更新
- docs/reference.md — 新增 runtime 层 Windows profile 说明、环境变量覆盖参考表
- docs/agent-install.md — 新增 Windows PowerShell 安装流程

**测试：**

- 新增 6 个测试覆盖 Windows 路径解析、shell 检测、二进制查找、PowerShell wrapper 生成、runtime install/uninstall 端到端流程
- 全量 28 个测试通过
