# 智能体安装 / Agent install

把下面的提示词复制给能读取 Git 仓库与执行本地命令的智能体。它先审计、后预览、最后在明确确认后写入。

```text
请使用 https://github.com/Jia-Ethan/claude-keysmith 帮我安装 Claude Code 本地指令文件。

先阅读 README.md、docs/reference.md、claude-instruct.py 和 examples/，确认工具、默认示例和目标路径。默认只运行 dry-run；不要直接写入。展示每个将被修改的路径、已有文件的备份路径、managed import block，以及（仅当我明确要求 --runtime 时）settings.json 和目标 shell profile（Windows 为 $PROFILE，macOS/Linux 为 ~/.zshrc）的具体变更。

等我明确确认后，才使用 --yes 写入。安装完成后运行 status；若安装 runtime，再运行 doctor。不要修改 Claude Code 二进制、MCP、网络、token、cookie、Base URL、其他 settings 字段或运行中进程。不要在输出、日志、文档或 Git 中暴露、复制或保存任何凭证。

Windows runtime 仅支持 Windows PowerShell 5.1 和 PowerShell 7。不要自行创建、替换或修补 ~/.local/bin/claude.ps1、~/.local/bin/claude.cmd；这些 launcher 属于 Claude Code 上游安装器。若发现旧 launcher，只按 claude-keysmith dry-run 显示的所有权判断与迁移计划处理；未知同名文件必须保持原样并报告冲突。无法从用户级 PSModulePath 识别 PowerShell profile 时，停止并请我通过 CLAUDE_KEYSMITH_SHELL_RC 指定，不要猜测。
```

## 推荐交互流程

### 项目级 import block

```bash
# 预览
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules

# 确认后写入
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes

# 验证
python3 claude-instruct.py status \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --json
```

### user-scope runtime

`--runtime` 会影响通过 managed shell wrapper 启动的后续 user-scope Claude Code 会话。先预览：

```bash
python3 claude-instruct.py install --scope user --runtime
```

确认路径与示例 prompt 后写入、加载 shell 函数并检查：

```bash
python3 claude-instruct.py install --scope user --runtime --yes
source ~/.zshrc
python3 claude-instruct.py status --scope user --runtime --json
python3 claude-instruct.py doctor --json
```

Windows PowerShell 使用：

```powershell
python .\claude-instruct.py install --scope user --runtime       # 先预览 profile、入口与旧 launcher
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
python .\claude-instruct.py doctor --json
```

对于 v5 升级或曾由安装 Agent 创建 `.local/bin/claude.ps1/.cmd` 的机器，必须保留第一次 dry-run 输出。只有工具将 `.ps1` 识别为旧 keysmith/prompt wrapper、将 `.cmd` 识别为同目录纯转发器时，才允许在用户确认后用 `--yes` 重命名到 timestamp 备份。任何未知文件冲突都必须在 runtime 写入前停止。

## 核验清单

安装智能体在写入前应说明：

1. scope 和目标 memory 文件；
2. 指令文件名与实际路径；
3. 将插入或替换的 managed import block；
4. 现有文件的 timestamp 备份；
5. 仅在 `--runtime` 下：`settings.systemPrompt`、可选 `max_tokens` 与 shell profile wrapper 的变更；
6. Windows runtime：PowerShell 5.1/7 profile、动态上游候选、旧 launcher 检测结果，以及需要设置的 `CLAUDE_KEYSMITH_SHELL_RC`；
7. 不会修改的内容：二进制、MCP、网络、凭证、Base URL、运行中进程和其他现有 settings 字段。

Windows runtime 写入后，`status --json` 应核对 `upstream_path`、`upstream_exists`、`shell_wrapper_current`、`legacy_launcher_detected`、`upgrade_required` 与 `runtime_ready`。`doctor` 只能展示安装类型、路径、候选拒绝原因与修复动作；输出中不得出现 Base URL、token 或 cookie。

验收需要在新 PowerShell 会话中验证正常启动、参数透传与非零退出码；真实 Ctrl+C 中断必须单独人工验证，不能用子进程返回 130 代替。发布 v6 前还需要分别在 Windows PowerShell 5.1、PowerShell 7，以及事故机或等价环境真实复测 `claude update`。不要把静态 status、dry-run 或尚未运行的 Actions 当作业务验收。

完整文件所有权、撤销与恢复语义见 [运行时参考](reference.md)。
