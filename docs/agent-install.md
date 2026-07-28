# 智能体安装 / Agent install

把下面的提示词复制给能读取 Git 仓库与执行本地命令的智能体。它先审计、后预览、最后在明确确认后写入。

```text
请使用 https://github.com/Jia-Ethan/claude-keysmith 帮我安装 Claude Code 本地指令文件。

先阅读 README.md、docs/reference.md、claude-instruct.py 和 examples/，确认工具、默认示例和目标路径。默认只运行 dry-run；不要直接写入。展示每个将被修改的路径、已有文件的备份路径、managed import block，以及（仅当我明确要求 --runtime 时）settings.json 和 ~/.zshrc 的具体变更。

等我明确确认后，才使用 --yes 写入。安装完成后运行 status；若安装 runtime，再运行 doctor。不要修改 Claude Code 二进制、MCP、网络、token、cookie、Base URL、其他 settings 字段或运行中进程。不要在输出、日志、文档或 Git 中暴露、复制或保存任何凭证。
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

`--runtime` 会影响通过 managed `claude()` shell wrapper 启动的后续 user-scope Claude Code 会话。先预览：

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

## 核验清单

安装智能体在写入前应说明：

1. scope 和目标 memory 文件；
2. 指令文件名与实际路径；
3. 将插入或替换的 managed import block；
4. 现有文件的 timestamp 备份；
5. 仅在 `--runtime` 下：`settings.systemPrompt`、可选 `max_tokens` 与 `~/.zshrc` wrapper 的变更；
6. 不会修改的内容：二进制、MCP、网络、凭证、Base URL、运行中进程和其他现有 settings 字段。

完整文件所有权、撤销与恢复语义见 [运行时参考](reference.md)。
