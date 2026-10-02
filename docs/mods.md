# 可选 Claude Code mod 后端

[English](mods.en.md)

这是使用官方 mods API 的社区插件，不是 Anthropic 官方插件，要求 **Claude Code 2.1.287 或更新版本**。插件自身的初始版本为 0.1.0。Python CLI、桌面客户端及默认安装方式保持不变。先迁移旧部署，再在新会话启用 mod，避免两条路径叠加。

## 加载与配置

启用前先检查 `examples/` 中的两份 Markdown。从包含插件文件的源码目录加载仓库根目录，即可在单次会话中试用：

```bash
claude --version
claude --plugin-dir /absolute/path/to/claude-keysmith
# 在新会话中运行：
/keysmith-status
```

**一次安装，后续自动加载：** 不必等 PR 合并，可以直接添加本机源码目录中的 marketplace，并以 `user` 范围安装。请将路径替换为本机目录：

```bash
claude plugin marketplace add /absolute/path/to/claude-keysmith
claude plugin install keysmith@keysmith-mods --scope user
```

退出已有 Claude Code 会话，之后直接运行 `claude` 即可，不需要 `--plugin-dir`，也不需要新增 shell wrapper。用户级安装适用于各项目；仍应先迁移原有的 Keysmith 注入。持久安装与 `--plugin-dir` 试用对应不同配置键，请使用下文的 `keysmith@keysmith-mods` 配置。

此改动合入上游 `main` 后，也可将 marketplace 来源设为上游仓库：

```bash
claude plugin marketplace add Jia-Ethan/claude-keysmith
claude plugin install keysmith@keysmith-mods --scope user
```

插件名为 **`keysmith`**：Claude Code 将 `claude-` 前缀保留给第一方插件。仓库名和旧 CLI 仍使用 `claude-keysmith`。

使用 `/plugin configure keysmith@keysmith-mods`（或 `/config` 中的插件选项）修改配置，再开新会话。也可以将以下条目合并到对应的 Claude Code 设置文件，保留其他字段。`--plugin-dir` 对应的键为 `keysmith@inline`，marketplace 安装对应 `keysmith@keysmith-mods`。

```json
{
  "pluginConfigs": {
    "keysmith@inline": {
      "options": {
        "mode": "runtime",
        "rulesFile": "",
        "appendFile": "",
        "registerAgent": true
      }
    }
  }
}
```

| 配置 | 默认值 | 行为 |
|---|---|---|
| `mode` | `runtime` | `runtime` 替换系统提示词；`context` 保留系统提示词，将规则加入首条消息的上下文。 |
| `rulesFile` | `""` | 使用内置 `examples/claude-project-rules.md`；非空时读取指定的本地绝对路径。 |
| `appendFile` | `""` | 使用内置 `examples/claude-append-prompt.md`；指定内容为空的文件可关闭追加文本。 |
| `registerAgent` | `true` | 用同一份规则和追加文本注册 `keysmith:keysmith`。 |

自定义路径必须是运行 Claude Code 的机器上的绝对路径：macOS/Linux 使用 `/path/file.md`，Windows 使用 `C:\path\file.md`。支持中文和空格；不接受相对路径、`~`、盘符相对路径或网络位置。规则正文不能为空，追加文件可以为空。

**runtime 模式会替换系统提示词。** 返回的章节只有 `keysmith:rules` 和非空时的 `keysmith:append`，顺序固定，均使用 `session` scope；其他系统提示词章节不保留。规则首个 H1 的去除方式与 Python runtime 一致。其他 mod 或组织策略仍可能改变 middleware 链的最终结果。

**context 模式只注入规则。** 保留已有上下文块、指令文件和默认系统提示词，主会话不注入追加文本。`registerAgent` 为 true 时仍会为独立 agent 读取追加文件；设为 false 可完全不读取追加文件。

Keysmith agent 在会话启动后注册，通过 **Agent 工具**委派，不支持启动参数 `--agent` 选择。可要求 Claude 明确委派给 `keysmith:keysmith`。它不替换旧 `--agent keysmith` 入口，也不修改其他 agent 定义。

## 本机快速测试

已有旧安装时，可以先在临时项目目录测试，避开原项目的 import；不必为了试用卸载原项目。用户级旧配置仍会被检查，若 `/keysmith-status` 报告冲突，应先按下文迁移，不能叠加验证。

以下适用于 macOS/Linux。在终端运行，将插件路径替换为本机源码目录。测试文件和配置全部放入临时目录，不修改现有设置或内置提示词：

```bash
keysmith_test_dir=$(mktemp -d)
cat > "$keysmith_test_dir/rules.md" <<'EOF'
# 测试规则
每次回答以 KEYSMITH_RULE_MARKER 开头。
EOF
cat > "$keysmith_test_dir/append.md" <<'EOF'
在规则标记之后、交付内容之前输出 KEYSMITH_APPEND_MARKER。
EOF
python3 - "$keysmith_test_dir" <<'PYCONFIG'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
options = {
    "mode": "runtime",
    "rulesFile": str(root / "rules.md"),
    "appendFile": str(root / "append.md"),
    "registerAgent": True,
}
(root / "settings.json").write_text(json.dumps({
    "pluginConfigs": {"keysmith@inline": {"options": options}}
}), encoding="utf-8")
PYCONFIG
cd "$keysmith_test_dir"
command claude --plugin-dir /absolute/path/to/claude-keysmith \
  --settings "$keysmith_test_dir/settings.json"
```

`command claude` 避开同名 shell function；若 PATH 中的可执行文件本身是旧 wrapper，还需按迁移步骤处理。这个测试沿用当前登录和模型提供方配置，调用模型会正常计费。

进入后先运行 `/keysmith-status`：确认 runtime 模式、来源是上述临时文件、没有冲突，并且提示词组成已验证。再发送：

```text
生成 Python 函数 add(a, b)，返回两数之和。
```

预期包含两个标记和正确函数。要求 Claude 委派同一任务给 `keysmith:keysmith`，可检查独立 agent；需要查看子 agent 的实际返回，不能只看主会话复述。修改测试配置中的 `mode` 为 `context`，退出并开新会话后，主会话预期只有规则标记。通过 `/plugin` 禁用插件后在新会话重复任务，预期两个标记均消失。单次标记测试确认注入路径，不证明复杂任务效果等价。

## 迁移旧部署

mod 在注入前执行只读检查，不安装或执行 Python、不删除文件、不修改 shell profile、不恢复设置、不修改权限。旧 CLI 的 JSON 契约及 `doctor --json` 固定字段不变。

1. 盘点各 scope 和指令名称，包括自定义名称：

   ```bash
   python3 claude-instruct.py status --scope user --runtime --json
   python3 claude-instruct.py status --scope project --project-dir /path/to/repo --json
   python3 claude-instruct.py status --scope local --project-dir /path/to/repo --json
   ```

2. 卸载前将自定义规则和追加文本保存到旧 `keysmith/` 目录**之外**，再通过插件选项填写新绝对路径。任何写操作前，先通过原 CLI 检查是否有待恢复事务。

3. 按实际安装的 scope/name 预览卸载。仅用户级 runtime 安装添加 `--runtime`；仅移除属于 Keysmith 的旧 agent 时添加 `--agents`。

   ```bash
   python3 claude-instruct.py uninstall --scope user --name YOUR_NAME --runtime --agents
   # 检查预览后执行：
   python3 claude-instruct.py uninstall --scope user --name YOUR_NAME --runtime --agents --yes
   ```

   project/local 使用对应命令清理 import 和 agent，对每个 managed name 分别处理。保留备份和事务日志。项目默认名称的卸载示例：

   ```bash
   python3 claude-instruct.py uninstall --scope project --project-dir .
   # 确认预览后，再加 --yes 执行
   ```

4. **`uninstall --runtime` 保留 `settings.systemPrompt`。** 若该字段仍属于 Keysmith，确认所有权后只移除这个字段，或用原恢复流程明确选择适当的受控备份。恢复整份设置备份可能撤销后续无关修改，应先检查，保留其他字段和凭证。

5. 重新加载 shell/profile，或打开新终端，确保之前已加载的 `claude` function 不再驻留。移除脚本和 alias 中的旧提示词参数。启用插件后打开**新会话**，运行 `/keysmith-status`。

旧配置冲突不会自动清理。已有 managed import、managed wrapper 或与 Keysmith 文本一致的 `settings.systemPrompt` 会暂停新注入；只发现旧 prompt 文件或独立旧 agent 时报告残留，不据此认定旧注入正在生效。

检测采用保守策略：磁盘上有旧 wrapper 即暂停注入，即使此次启动未加载它。扫描范围包括项目祖先目录中的指令文件、用户级指令、标准 zsh 和 Documents 下的 PowerShell profile，以及显式 `CLAUDE_KEYSMITH_SHELL_RC`。context hook 还检查已加载的旧指令文本；符号链接或 import 副本可通过已加载文本与 Keysmith 路径识别。无标记自定义 alias、非标准 profile、已删除但仍驻留的 function 和显式 CLI 提示词参数无法穷尽检测。配置冲突与残留分别报告，配置冲突不等同于证明旧注入已经发送给模型。

## 验证与限制

`/keysmith-status` 报告模式、来源路径、agent 注册状态、旧配置检测及 hook 调用记录。runtime 状态还探测提示词组成，将最终章节 ID、**文本**和 scope 与期望值逐一比较。这只证明探测当时的组成，不证明之前的请求或已有提示词快照发送了什么。context 状态报告其 hook 是否运行，不宣称后续 hooks 保留了上下文。

配置变更、清理、启用/禁用、重载或更新后，应开新会话。提示词快照、恢复会话和压缩可能改变 hooks 的渲染时机。源文件在每次模块加载时只读取一次；修改 Markdown 后需要新会话或插件重载。读取或冲突检查失败时保留原提示词/上下文，不注册可选 agent；诊断不打印提示词正文、设置对象、凭证或原始异常。

组织管理的会话可能加载内置 `sec-default` mod，跳过用户级 `prompt.compose` 和 `prompt.context` hooks。插件出现在列表或 agent 注册成功，不证明主会话注入成功。状态报告未验证或组成变化，遵守宿主策略，不通过改写 `prompt.submit` 或放宽权限降级注入。见 [sec-default 官方源码](https://github.com/anthropics/claude-code/tree/684800b206824dfd0cc8a876e8604b20f72c3617/mods/sec-default)。

通过 Claude Code 插件命令禁用或卸载。`disableAllHooks`、安全模式或宿主策略禁用插件后，状态命令也无法运行。禁用 mod 不会恢复已有会话的提示词快照，应在新会话验证。

只有独立注册的 Keysmith agent 明确持有所选规则和追加文本。Explore、Plan、自定义 agent、SDK 预设和 teammate 提示词各自有独立组成路径，应分别测试。注入载体的工程等价不证明模型行为等价。本地证据见 [mod-acceptance.md](mod-acceptance.md)。

## 开发验证

```bash
python3 -m pytest -q tests
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate .claude-plugin/marketplace.json --strict
claude plugin test .
python3 tools/test_mod.py
```

`tools/test_mod.py` 只复制插件文件、内置示例、原生测试和 LICENSE 到临时目录，校验两种清单，使用原生 `claude-code/testing` 引擎测试 runtime、带/不带 agent 的 context，以及含中文和空格的自定义路径。不需要凭证或调用模型。Windows CI 使用 Windows 绝对路径，macOS/Linux 使用 POSIX 路径。测试刻意排除本机未跟踪的 `CLAUDE.md`/`.claude/`，因为根目录 `CLAUDE.md` 会触发插件严格校验警告。

CI 在 Linux、macOS、Windows 固定使用 **Claude Code 2.1.287**。运行时 hooks 不依赖 Node.js 或 Python；它们仅用于开发验证及 CLI 安装。

官方参考：[mods 概览](https://code.claude.com/docs/en/plugins/mods/overview)、[mods API](https://code.claude.com/docs/en/plugins/mods/reference)。
