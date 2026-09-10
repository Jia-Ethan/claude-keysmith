<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

## 简体中文

```text
请从公开仓库安装 claude-keysmith v7.2。只使用 tag `v7.2` 或对应 GitHub Release，不要从浮动 main 安装。检出后确认当前 checkout 精确匹配 `v7.2`，并校验 examples/claude-project-rules.md 的 SHA-256 为 `d15aa6b25ee39b672abe79e215d9731bd083b48b57c4a5aad2e07a37dc09c94e`，examples/claude-append-prompt.md 的 SHA-256 为 `e41a0f41d607d792ccfef233e768df1ce5c565b6e21b07f62bad8a90d119e76b`。旧 tag `v7.1` 里的提示词仍是 v4.0 说明书，不能用来校验当前短规则脸。运行 --version、install（无 --yes）和 status，报告目标 CLAUDE.md / CLAUDE.local.md、managed import block、指令文件路径与 SHA-256、备份计划；仅当我明确要求 --runtime 时，再报告 settings.json 与 shell profile（Windows 为 $PROFILE，macOS/Linux 为 ~/.zshrc）的变更。如果 status 发现 durable journal，只预览 recover 并等我确认后才添加 --yes。等我明确确认后才使用 --yes 写入。完成后开一个新 Claude Code 会话，验证 import block 已加载。不要删除任何备份或事务日志，不修改 Claude Code 二进制、MCP、网络、token、cookie、Base URL、其他 settings 字段或运行中进程。Windows runtime 不要自行创建或替换 ~/.local/bin/claude.ps1、claude.cmd。
```

## English

```text
Install claude-keysmith v7.2 from the public repository. Use only the `v7.2` tag or the matching GitHub Release; do not install from floating `main`. After checkout, confirm the working tree matches the `v7.2` tag exactly, and verify that the SHA-256 of examples/claude-project-rules.md is `d15aa6b25ee39b672abe79e215d9731bd083b48b57c4a5aad2e07a37dc09c94e` and that examples/claude-append-prompt.md is `e41a0f41d607d792ccfef233e768df1ce5c565b6e21b07f62bad8a90d119e76b`. The prompt inside the old `v7.1` tag is still the v4.0 manual and must not be used to verify the current short lab face. Run --version, install without --yes, and status, then report the target CLAUDE.md / CLAUDE.local.md, the managed import block, the instruction-file path and SHA-256, and the backup plan. Only if I explicitly ask for --runtime, also report settings.json and the shell profile (Windows $PROFILE, macOS/Linux ~/.zshrc). If status finds a durable journal, only preview recover and wait for my confirmation before adding --yes. Do not write until I explicitly confirm --yes. When finished, open a new Claude Code session and verify that the import block is loaded. Do not delete any backups or transaction journals, and do not modify the Claude Code binary, MCP, network, tokens, cookies, Base URL, other settings fields, or running processes. For Windows runtime, do not create or replace ~/.local/bin/claude.ps1 or claude.cmd.
```

## 推荐交互流程 / Suggested flow

### 项目级 import block

```bash
python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules

python3 claude-instruct.py install \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --yes

python3 claude-instruct.py status \
  --scope project \
  --project-dir /path/to/repo \
  --name claude-project-rules \
  --json
```

### user-scope runtime

```bash
python3 claude-instruct.py install --scope user --runtime
python3 claude-instruct.py install --scope user --runtime --yes
source ~/.zshrc
python3 claude-instruct.py status --scope user --runtime --json
python3 claude-instruct.py doctor --json
```

Windows PowerShell:

```powershell
python .\claude-instruct.py install --scope user --runtime
python .\claude-instruct.py install --scope user --runtime --yes
. $PROFILE
python .\claude-instruct.py status --scope user --runtime --json
python .\claude-instruct.py doctor --json
```

完整文件所有权、撤销与恢复语义见 [运行时参考](reference.md)。
