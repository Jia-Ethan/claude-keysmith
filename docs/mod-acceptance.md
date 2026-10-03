# mod 后端验收记录

[English](mod-acceptance.en.md)

记录日期：**2026-10-02**。基于上游 `b3d8cc2`，在 macOS 上使用 Claude Code **2.1.287**。测试采用临时插件副本、全新的工作区和配置目录、当前配置的模型提供方及无害的自定义 Markdown；没有改动用户的实际部署或清理现有配置。

## 自动化验证

- 上游完整 Python 测试：**155 通过**。
- 原生 hooks 测试：通过 `python3 tools/test_mod.py` 运行 **21 个用例 × 4 种配置 = 84 通过**，覆盖内置 runtime、带/不带 agent 的 context，以及含中文和空格的自定义绝对路径。
- 每种配置的插件和 marketplace 清单均通过严格校验。
- 补充 TypeScript 严格检查通过，使用 Anthropic 提交 `684800b206824dfd0cc8a876e8604b20f72c3617` 的已发布类型声明。该生成文件头标注 2.1.277；目标版本兼容性由 2.1.287 原生校验、测试及真实会话验证，不依赖旧版本文件头作判断。
- 原生策略夹具覆盖组织级提示词 hooks 跳过及插件拒绝加载，不代替真实 Team/Enterprise 组织账号验收。
- CI 在 Linux、macOS、Windows 固定使用 2.1.287。仅本机执行不能证明 Windows 文件系统或 PowerShell 兼容性；Windows CI 使用 Windows 自定义绝对路径。

## 真实会话

测试规则文件原文：

```markdown
# Smoke rules

For this smoke test, begin each answer with KEYSMITH_RULE_MARKER.
```

测试追加文件原文：

```text
After the beginning marker, include KEYSMITH_APPEND_MARKER before the deliverable.
```

测试任务原文：`Return a Python function add(a, b) that returns their sum. Output the function only.`

这些英文片段保留实际测试输入，避免翻译后与验收记录不一致。

| 新会话 | 实际结果 |
|---|---|
| `claude -p`，mod runtime | 两个标记及正确的 `return a + b` 函数。 |
| `claude -p`，旧 `--system-prompt-file` + `--append-system-prompt-file` | 两个标记及相同函数，格式略有差异。 |
| `claude -p`，mod context | 规则标记和函数，没有追加标记。 |
| `claude -p`，通过 `disableAllHooks: true` 禁用 mod | 只有函数，没有两个标记。 |
| 交互 CLI，runtime | `/keysmith-status` 验证提示词组成；任务返回两个标记和函数。 |
| Agent 工具委派给 `keysmith:keysmith` | 记录到实际 Agent 调用；子 agent 的工具返回含两个标记和函数。 |
| Agent 工具委派给 `Explore` | 实际子 agent 返回函数，不含 Keysmith 标记。 |
| Agent 工具委派给 `Plan` | 实际子 agent 返回函数与规划文字，不含 Keysmith 标记。 |

非交互模型调用只开放无工具或 Agent 工具，权限模式为 `dontAsk`，每次调用均限制预算和轮数。上表 agent 结果指**子 agent 的工具返回**，不是主会话的最终回答；主会话仍使用自身的 Keysmith 标记。

另通过 `pluginConfigs["keysmith@inline"].options` 向非交互会话提供插件配置，运行 `/keysmith-status`，确认自定义文件来源、agent 注册，以及最终组成的 ID、文本和 scope。

在临时配置目录添加本地 marketplace，安装 `keysmith@keysmith-mods`。随后不带 `--plugin-dir` 启动新的非交互会话，使用 `keysmith@keysmith-mods` 配置键，成功运行 `/keysmith-status` 并验证提示词组成。用户实际插件安装未改动。

启动参数 `--agent keysmith:keysmith` 返回 “not found”，因为动态注册晚于启动 agent 选择。应按 [使用说明](mods.md) 通过 Agent 工具委派；旧 agent 载体仍支持原启动用法。

## 适用限制

这是注入路径的小型冒烟测试，不是效果基准测试，也不证明模型表现与 Keysmith 已公布结果一致。它确认了测试主会话及独立注册 agent 接收到自定义文本，**不证明普遍继承**：Explore 和 Plan 未出现这些标记。

真实模型测试使用自定义 Markdown，尚未对仓库内置完整提示词开展系统性效果评测。没有宣称完成 SDK、Desktop/VS Code、teammate、恢复会话或真实组织策略验收。测试启用/禁用或提示词配置变更时，需开新会话。
