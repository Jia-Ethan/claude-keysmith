<!-- markdownlint-disable MD013 -->
# JSON 契约参考：`claude-keysmith/v1`

`claude-instruct.py` 的所有自动化接口命令在传入 `--json` 时输出稳定 JSON，顶层 `schema` 为 `claude-keysmith/v1`。本文件逐命令列出字段与示例。GUI 与任何外部调用方都应只消费本契约，不解析人类可读文本输出。

## 通用规则

- **一个 JSON 文档**：契约 JSON 打印到 stdout。除 `doctor` 外，顶层都含 `schema` 字段。
- **preview / execute 两种模式**：写操作（`install` / `uninstall` / `restore` / `recover`）默认输出 `mode: "preview"`（不落盘）；加 `--yes` 后输出 `mode: "execute"`。`--dry-run` 是兼容参数，行为与不加 `--yes` 相同。
- **失败关闭（fail-closed）**：
  - `blockers` 非空 ⇒ `ok: false`、`exit_status: 1`，命令不做任何写入。
  - `ok: false` ⇒ 调用方必须视为失败并停止后续动作，即使 exit code 为 0 的场景也不存在——非零 exit 与 `ok:false` 同时成立。
  - 未捕获异常同样以 `ok: false` + `error` 输出 JSON（不丢 Python traceback 给调用方）。
  - **参数校验失败**（如 `--max-tokens 0`）在传入 `--json` 时也输出契约 JSON 到 stdout（`ok: false`、`exit_status: 2`，`error` / `blockers` 为 argparse 的具体原因），argparse 的 usage 文本仍保留在 stderr 供人工阅读；进程退出码为 2。
  - GUI 侧的 proceed 判定见 `gui/src/lib/parser.js` 的 `gateReport`：`exit_code !== 0`、`blockers` 非空、`ok === false` 任一成立即 blocked。
- **凭证脱敏**：契约与文本输出都不包含 API token、cookie、Base URL 或非目标的 `settings.json` 字段值。`settings.json` 仅以路径（`settings_file`）和布尔对齐状态（`settings_system_prompt_aligned`）出现；`doctor` 更是固定 9 个键，永不扩展出凭证字段。
- **sha256 / size_bytes**：`backups[]`、`source`/`sources`、`status.source_identity` 中的指纹均为 SHA-256 十六进制 + 字节数，供调用方核验内容，不展示内容本身。

## 写操作报告的共同骨架

`install` / `uninstall` / `restore` / `recover` 的 preview 与 execute 报告共享以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | string | 固定 `"claude-keysmith/v1"` |
| `operation` | string | `install` / `uninstall` / `restore` / `recover` |
| `mode` | string | `"preview"`（无 `--yes`）或 `"execute"`（有 `--yes`） |
| `ok` | bool | `false` 即失败关闭 |
| `scope` | string\|null | `user` / `project` / `local` |
| `name` | string\|null | 指令名（`claude-project-rules`）；`restore`/`recover` 为 `null` |
| `target` | object | 按 operation 不同，见各命令小节 |
| `source` | object\|null | 指令来源 `{kind, path, size_bytes, sha256}`（install / restore） |
| `sources` | object | 仅 runtime install：`{system_prompt: {...}, append: {...}}`，同 `source` 结构 |
| `actions[]` | array | `{action, path, detail}`，preview 中是计划动作，execute 中是已执行动作（execute 中 `backup` 动作合并进 `backups[]` 证据列表） |
| `warnings[]` | array | 非阻塞提示，如上游入口缺失、`settings.systemPrompt` 保留 |
| `blockers[]` | array | 阻塞项；非空即失败关闭 |
| `backups[]` | array | 备份证据，见下表 |
| `reload_required` | bool | runtime 写入后需要重载 shell/profile 时为 `true` |
| `reload_hint` | string\|null | 例如 `source ~/.zshrc` 或 `. $PROFILE` |
| `exit_status` | int | 进程退出码（0 成功，1 失败关闭） |
| `error` | string\|null | 失败原因摘要 |
| `journal_id` | string\|null | 仅 execute 且走了事务日志时存在 |
| `runtime` | object\|null | 仅 runtime install：写入后的 runtime 状态（与 `status` 的 `runtime` 块同构；preview 时为计划状态） |

`backups[]` 条目（execute 实际备份 / preview 计划备份）：

| 字段 | 说明 |
|---|---|
| `target` | 被备份文件路径 |
| `backup_path` | 备份文件路径；preview 阶段为 `null` |
| `sha256` / `size_bytes` | execute 时为备份文件指纹；preview 时为当前目标文件指纹 |
| `created` | 从备份文件名解析出的 ISO 时间；preview 为 `null` |
| `planned` | 仅 preview 条目出现且为 `true` |

`actions[].action` 的取值随命令不同：`backup` / `write` / `remove` / `migrate` / `align-settings` / `install-wrapper` / `remove-wrapper` / `clear-recovery-marker` / `reclaim-lock` / `restore-moved` / `cleanup` / `cleanup-journal` / `cleanup-atomic-temp` / `noop`。

## `install --json`

target 在 runtime 安装时扩展为包含 `system_prompt_file`、`append_prompt_file`、`settings_file`、`shell_rc`、`shell_kind`、`upstream_path`、`upstream_exists`。

执行示例（已脱敏：临时 HOME 替换为 `~`，上游入口路径替换为占位符）：

```json
{
  "schema": "claude-keysmith/v1",
  "operation": "install",
  "mode": "execute",
  "ok": true,
  "scope": "user",
  "name": "claude-project-rules",
  "target": {
    "memory_file": "~/.claude/CLAUDE.md",
    "instruction_file": "~/.claude/keysmith/claude-project-rules.md",
    "import_target": "@keysmith/claude-project-rules.md",
    "system_prompt_file": "~/.claude/keysmith/system-prompt.md",
    "append_prompt_file": "~/.claude/keysmith/append-prompt.md",
    "settings_file": "~/.claude/settings.json",
    "shell_rc": "~/.zshrc",
    "shell_kind": "zsh",
    "upstream_path": "~/.local/share/claude/versions/<version>",
    "upstream_exists": true
  },
  "actions": [
    {"action": "write", "path": "~/.claude/CLAUDE.md", "detail": "install/update managed import block"},
    {"action": "write", "path": "~/.claude/keysmith/claude-project-rules.md", "detail": "write keysmith instruction file"},
    {"action": "write", "path": "~/.claude/keysmith/system-prompt.md", "detail": "write system-prompt.md"},
    {"action": "write", "path": "~/.claude/keysmith/append-prompt.md", "detail": "write append-prompt.md"},
    {"action": "align-settings", "path": "~/.claude/settings.json", "detail": "align settings.systemPrompt"},
    {"action": "install-wrapper", "path": "~/.zshrc", "detail": "install/update managed shell wrapper"}
  ],
  "warnings": [],
  "blockers": [],
  "backups": [],
  "reload_required": true,
  "reload_hint": "source ~/.zshrc",
  "exit_status": 0,
  "error": null,
  "source": {
    "kind": "bundled",
    "path": "<repo>/examples/claude-project-rules.md",
    "size_bytes": 3927,
    "sha256": "fce8628a…86b35a"
  },
  "sources": {
    "system_prompt": {"kind": "bundled", "path": "<repo>/examples/claude-project-rules.md", "size_bytes": 3859, "sha256": "28fcdb13…32a0837"},
    "append": {"kind": "bundled", "path": "<repo>/examples/claude-append-prompt.md", "size_bytes": 176, "sha256": "03322328…e953f0"}
  },
  "runtime": {
    "supported": true,
    "shell_kind": "zsh",
    "system_prompt_exists": true,
    "append_prompt_exists": true,
    "settings_system_prompt_aligned": true,
    "shell_wrapper_present": true,
    "shell_wrapper_managed": true,
    "shell_wrapper_current": true,
    "upstream_path": "~/.local/share/claude/versions/<version>",
    "upstream_exists": true,
    "legacy_launcher_detected": false,
    "legacy_launcher_conflict": false,
    "upgrade_required": false,
    "runtime_ready": true
  },
  "journal_id": "18fc457d49c347339806f9e76a987074"
}
```

已存在的文件会先产生 `backup` 动作并在 `backups[]` 中给出实际备份证据（本例为首次安装，故为空）。上游入口不存在时不阻塞安装，而是进入 `warnings[]`（wrapper 运行时再解析）。

## `uninstall --json`

骨架同上；`--runtime` 时追加 `system_prompt_file` / `append_prompt_file` / `shell_rc` 移除计划，并给出警告 `settings.systemPrompt left intact (restore from a controlled backup to roll it back)`。预览示例（截选）：

```json
{
  "schema": "claude-keysmith/v1",
  "operation": "uninstall",
  "mode": "preview",
  "ok": true,
  "scope": "user",
  "name": "claude-project-rules",
  "actions": [
    {"action": "backup", "path": "~/.claude/CLAUDE.md", "detail": "back up memory file before import block removal"},
    {"action": "write", "path": "~/.claude/CLAUDE.md", "detail": "remove managed import block"},
    {"action": "backup", "path": "~/.claude/keysmith/claude-project-rules.md", "detail": "back up instruction file before removal"},
    {"action": "remove", "path": "~/.claude/keysmith/claude-project-rules.md", "detail": "remove keysmith instruction file"}
  ],
  "warnings": ["settings.systemPrompt left intact (restore from a controlled backup to roll it back)"],
  "blockers": [],
  "backups": [
    {"target": "~/.claude/CLAUDE.md", "backup_path": null, "sha256": "9e6eba77…6c5ffc04", "size_bytes": 146, "created": null, "planned": true}
  ],
  "reload_required": true,
  "reload_hint": "source ~/.zshrc",
  "exit_status": 0,
  "error": null
}
```

## `restore --json`

`--target` 与 `--backup` 必填；`--scope` / `--project-dir` 可选。传入 `--scope` 时，`target` / `backup` 必须与该 scope 的 `backups --json` 输出中的 `target_path` / `backup_path` 精确配对，否则在 preview 与 execute 都失败关闭；不传 `--scope` 才保留 CLI 高级用户使用的非受控恢复路径。新增字段：

| 字段 | 说明 |
|---|---|
| `target.file` / `target.backup` | 目标与备份路径 |
| `managed` | 带 scope 时表示 target / backup 是否为 `backups --json` 枚举出的精确配对；无 scope 时按 `<target>.bak_YYYYMMDD_HHMMSS…` 同目录规则判断。`managed: true` 的恢复走 journal/lock 事务；`false` 仅用于无 scope 的 CLI 高级恢复路径 |
| `recovery_marker_cleared` | 受控恢复 user scope `settings.json` 且恢复的 `systemPrompt` 与 `system-prompt.md` 一致时，清除待恢复标记并置 `true` |

执行示例（受控恢复）：

```json
{
  "schema": "claude-keysmith/v1",
  "operation": "restore",
  "mode": "execute",
  "ok": true,
  "scope": "user",
  "target": {
    "file": "~/.claude/CLAUDE.md",
    "backup": "~/.claude/CLAUDE.md.bak_20260814_015807"
  },
  "managed": true,
  "actions": [
    {"action": "backup", "path": "~/.claude/CLAUDE.md", "detail": "pre-restore safety backup of current target"},
    {"action": "write", "path": "~/.claude/CLAUDE.md", "detail": "restore content from CLAUDE.md.bak_20260814_015807"}
  ],
  "backups": [
    {
      "target": "~/.claude/CLAUDE.md",
      "backup_path": "~/.claude/CLAUDE.md.bak_20260814_015824_pre_restore",
      "sha256": "9e6eba77…6c5ffc04",
      "size_bytes": 146,
      "created": "2026-08-14T01:58:24"
    }
  ],
  "source": {"kind": "backup", "path": "~/.claude/CLAUDE.md.bak_20260814_015807", "size_bytes": 146, "sha256": "9e6eba77…6c5ffc04"},
  "warnings": [],
  "blockers": [],
  "reload_required": false,
  "reload_hint": null,
  "recovery_marker_cleared": false,
  "exit_status": 0,
  "error": null,
  "journal_id": "74daa4d09a9d49ce9c49f264eb50cd8e"
}
```

恢复前会再为当前目标生成 `*_pre_restore` 安全备份。

## `status --json`

只读。保留全部历史扁平键（`memory_file`、`instruction_file`、`import_target`、`*_exists`、`installed`），并新增结构化块：

| 块 | 字段 |
|---|---|
| `presence` | `memory_file`、`instruction_file`、`import_block`、`system_prompt`、`append_prompt`、`settings_file`、`shell_wrapper`（后四项仅 `--runtime` 时填充） |
| `alignment` | `import_block_present`、`import_target`、`settings_system_prompt_aligned`、`shell_wrapper_current`、`shell_wrapper_managed` |
| `source_identity` | `kind`（`deployed`/`missing`）、`instruction_sha256`、`instruction_size_bytes`、`drift`、`system_prompt_sha256`、`settings_system_prompt_drift` |
| `runtime_readiness` | `upstream_candidates`、`upstream_path`、`upstream_exists`、`shell_wrapper_current`、`upgrade_required`、`legacy_launcher_detected`、`legacy_launcher_paths`、`legacy_launcher_conflict`、`legacy_launcher_conflict_paths`、`runtime_ready`（仅 user scope `--runtime`） |
| `recovery_state` | `journals`、`journal_count`、`atomic_temp_files`、`atomic_temp_count`、`conflicts`、`lock_present`、`lock_live`、`recovery_required`、`must_recover_before_writes` |
| `runtime` | 完整 runtime 状态（仅 user scope `--runtime`；非 user scope 为 `{supported: false, reason: ...}`） |

`recovery_state.journals[]` 条目：`{journal_path, journal_id, operation, state, started_at, pid}`。`runtime_ready` 只有在 prompt 文件完整、settings 对齐、wrapper 为当前 v7.1 模板、上游入口存在且无旧 launcher 冲突时才为 `true`。

示例（未安装，user scope + `--runtime`，截选）：

```json
{
  "schema": "claude-keysmith/v1",
  "scope": "user",
  "root": "~/.claude",
  "memory_file": "~/.claude/CLAUDE.md",
  "instruction_file": "~/.claude/keysmith/claude-project-rules.md",
  "import_target": "@keysmith/claude-project-rules.md",
  "memory_file_exists": false,
  "instruction_file_exists": false,
  "import_block_exists": false,
  "installed": false,
  "presence": {"memory_file": false, "instruction_file": false, "import_block": false, "system_prompt": false, "append_prompt": false, "settings_file": false, "shell_wrapper": false},
  "alignment": {"import_block_present": false, "import_target": "@keysmith/claude-project-rules.md", "settings_system_prompt_aligned": false, "shell_wrapper_current": false, "shell_wrapper_managed": false},
  "source_identity": {"kind": "missing", "instruction_sha256": null, "instruction_size_bytes": null, "drift": null, "system_prompt_sha256": null, "settings_system_prompt_drift": null},
  "recovery_state": {"journals": [], "journal_count": 0, "atomic_temp_files": [], "atomic_temp_count": 0, "conflicts": [], "lock_present": false, "lock_live": false, "recovery_required": false, "must_recover_before_writes": false},
  "runtime_readiness": {"upstream_candidates": [], "upstream_path": null, "upstream_exists": false, "shell_wrapper_current": false, "upgrade_required": true, "legacy_launcher_detected": false, "legacy_launcher_paths": [], "legacy_launcher_conflict": false, "legacy_launcher_conflict_paths": [], "runtime_ready": false}
}
```

## `backups --json`

只读。只枚举 keysmith 创建的、能通过 `^(?P<target>.+)\.bak_(?P<ts>\d{8}_\d{6})(?:_(?P<rest>.*))?$` 校验的备份文件，不会把任意文件当备份。扫描位置：scope 根目录（`kind: "memory"`）、keysmith 目录（`kind: "instruction"`）；user scope 额外包含 runtime keysmith 目录（`kind: "runtime"`）、shell profile 所在目录（`kind: "shell_rc"`）与 `~/.local/bin`（`kind: "legacy_launcher"`）。

| 字段 | 说明 |
|---|---|
| `backups[]` | `{backup_path, target_name, target_path, sha256, size_bytes, created, kind}`；GUI 必须把绝对 `target_path` 原样传给 scoped restore，不能只传 basename |
| `count` | 条目数 |
| `scope_root` | scope 根目录 |

示例（含一条备份）：

```json
{
  "schema": "claude-keysmith/v1",
  "operation": "backups",
  "ok": true,
  "scope": "user",
  "scope_root": "~/.claude",
  "backups": [
    {
      "backup_path": "~/.claude/CLAUDE.md.bak_20260814_015807",
      "target_name": "CLAUDE.md",
      "target_path": "~/.claude/CLAUDE.md",
      "sha256": "9e6eba77…6c5ffc04",
      "size_bytes": 146,
      "created": "2026-08-14T01:58:07",
      "kind": "memory"
    }
  ],
  "count": 1,
  "exit_status": 0,
  "error": null
}
```

GUI 的恢复界面只从这里取备份列表，不提供任意 target/backup 输入。

## `recover --json`

默认 preview，`--yes` 执行；重复执行幂等。在写操作骨架上新增：

| 字段 | 说明 |
|---|---|
| `residue[]` | 发现的残留：`{kind: "journal", journal_path, journal_id, operation, state, started_at, pid, steps}`、`{kind: "corrupt_journal", journal_path}`、`{kind: "atomic_temp", path}`、`{kind: "settings_recovery_marker", path}` |
| `planned_repairs[]` | 计划修复：`rollback-pending`（回滚未提交事务）、`finalize-committed`（核验已提交事务并清理 journal）、`cleanup-atomic-temp`（删除 keysmith 专属原子写临时残留）、`clear-settings-marker`（settings 对齐后清除待恢复标记） |

无残留示例：

```json
{
  "schema": "claude-keysmith/v1",
  "operation": "recover",
  "mode": "preview",
  "ok": true,
  "scope": "user",
  "target": {"keysmith_dir": "~/.claude/keysmith", "scope_root": "~/.claude"},
  "actions": [{"action": "noop", "path": "~/.claude/keysmith", "detail": "no transaction residue found"}],
  "residue": [],
  "planned_repairs": [],
  "warnings": [],
  "blockers": [],
  "backups": [],
  "reload_required": false,
  "reload_hint": null,
  "exit_status": 0,
  "error": null
}
```

发现活跃锁（另一进程正在写）时 preview 即 `ok: false`、`exit_status: 1` 并给出 blocker，不做任何修改。

## `doctor --json`

键集合固定为 9 个，受契约测试约束，永不扩展出凭证字段：

`installation_type`、`upstream_candidates`、`upstream_path`、`system_prompt_file`、`append_prompt_file`、`settings_file`、`shell_kind`、`shell_rc`、`repair_actions`。

```json
{
  "installation_type": "path",
  "upstream_candidates": [
    {"kind": "path", "path": "~/.local/share/claude/versions/<version>", "exists": true, "eligible": true, "reason": "available"}
  ],
  "upstream_path": "~/.local/share/claude/versions/<version>",
  "system_prompt_file": "~/.claude/keysmith/system-prompt.md",
  "append_prompt_file": "~/.claude/keysmith/append-prompt.md",
  "settings_file": "~/.claude/settings.json",
  "shell_kind": "zsh",
  "shell_rc": "~/.zshrc",
  "repair_actions": ["No repair action required."]
}
```

注意：`doctor` 无顶层 `schema` 键（历史原因保留固定键集合），GUI 按固定键解析而非按 `schema` 分流。

## 命令行参数对照

JSON 输出的触发与语义由以下 argparse 参数决定（见 `build_parser()`）：

| 命令 | 参数 |
|---|---|
| `install` | `--scope`（必填）、`--project-dir`、`--name/-n`、`--file/-f`、`--runtime`、`--append-file`、`--max-tokens`（正整数，argparse `type=positive_int`，0/负数/非数字直接 usage error）、`--dry-run`、`--yes`、`--json` |
| `status` | `--scope`（必填）、`--project-dir`、`--name`、公共参数；`--runtime`、`--json` |
| `uninstall` | `--scope`（必填）、`--project-dir`、`--name`；`--runtime`、`--dry-run`、`--yes`、`--json` |
| `restore` | `--target`（必填）、`--backup`（必填）、`--scope`（可选）、`--project-dir`、`--dry-run`、`--yes`、`--json` |
| `backups` | `--scope`（必填）、`--project-dir`、`--json` |
| `recover` | `--scope`（必填）、`--project-dir`、`--dry-run`、`--yes`、`--json` |
| `doctor` | `--json` |

`--runtime` 仅在 `--scope user` 下有效，其余 scope 传入会失败关闭。
