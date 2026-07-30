# Changelog

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