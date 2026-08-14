<!-- markdownlint-disable MD013 -->
# 隐私与安全边界

本文列出 CLI（`claude-instruct.py`）与桌面客户端（`gui/`）明确不做的事，以及为收窄攻击面而做的工程约束。这些边界同时被代码、契约测试与文档约束。

## 永不触碰的内容

CLI 与 GUI 都不会读取、修改或传输：

- Claude Code 二进制、launcher 或任何运行中的进程（Windows 升级时仅把**确认属于旧 keysmith wrapper** 的 `~/.local/bin/claude.ps1`/`claude.cmd` 重命名为 timestamp 备份；无法确认所有权的同名文件原样保留并报告冲突）。
- 网络：无遥测、无上报、无更新检查、无任何出站请求。GUI 的 CSP 为 `default-src 'self'` + 本地 IPC，前端不加载远程资源。
- MCP 配置、hooks、permissions。
- API token、cookie、Base URL，以及 `settings.json` 中除对齐目标（顶层 `systemPrompt`，及显式 `--max-tokens` 时的顶层 `max_tokens`）以外的所有字段。

## 输出与凭证脱敏

- `settings.json` 的内容从不进入任何输出：JSON 契约里只有路径（`settings_file`）与布尔对齐状态（`settings_system_prompt_aligned`）。
- `doctor --json` 的键集合固定为 9 个（`installation_type`、`upstream_candidates`、`upstream_path`、`system_prompt_file`、`append_prompt_file`、`settings_file`、`shell_kind`、`shell_rc`、`repair_actions`），由契约测试断言，防止未来改动意外带出 settings 字段或凭证。
- 备份与 source 证据只含 `sha256` / `size_bytes` 指纹，不含文件内容。
- `settings.json` 中的 `"claude-keysmith recovery marker"` 是 keysmith 自用的恢复标记键（布尔值），不含任何凭证语义。

## GUI 进程边界

- CLI 一律以 argv 数组启动（`Command::new(...).args([...])`），从不经过 shell 字符串拼接；前端构造的参数也是字符串数组（`parser.js` 的 `build*Args`）。
- stdout/stderr 各封顶 2 MiB；超限继续排空但以"输出不完整"失败关闭，不基于截断 JSON 做决策。
- 超时（默认 30 s，写操作 120 s，版本探测 15 s）杀死整棵进程树：Unix 独立进程组 + `kill(-pid)`，Windows `taskkill /T /F`；另有 `kill_on_drop`。
- 单实例（二次启动聚焦已有窗口）；全局写互斥（前端操作租约）；关闭屏障保证有活动操作时退出排队，而不是中断 CLI 写事务。
- CLI 定位 sidecar 优先，`.py` 脚本回退需要系统 Python；`CLAUDE_KEYSMITH_CLI` / `CLAUDE_KEYSMITH_PYTHON` 环境变量可显式覆盖。

## 文件系统边界

- 写入目标仅限：scope 的 memory 文件与 keysmith 目录、（user scope runtime）`~/.claude/settings.json`、shell profile，以及 Windows 旧 launcher 的确认迁移。每个目标在写入前都有 preview 可见。
- GUI 的"最近项目"只记录用户通过文件对话框**显式选择过**的路径（最多 12 条），永不扫描磁盘。
- 所有写操作默认 preview，必须显式确认（CLI `--yes` / GUI 确认对话框）才执行；写前备份、事务化、可恢复（见 [`transaction-recovery.md`](transaction-recovery.md)）。

## 恢复边界

- GUI 的恢复界面只展示 `backups --json` 枚举出的 keysmith 受控备份（命名规则 `<target>.bak_YYYYMMDD_HHMMSS…` 且与目标同目录），**不提供任意 target/backup 对**的恢复入口；自由恢复保留为 CLI-only 高级路径（`restore --target --backup`）。
- `uninstall --runtime` 不自动回滚 `settings.systemPrompt`；回滚必须显式选择受控备份执行 restore。

## 明确不做的事（发布边界）

- 无自动更新、无代码签名 / notarization / Authenticode、无 Linux GUI。
- 不验证既有会话是否重新加载指令；部署后请开新会话做 smoke test。
- 不承诺覆盖 Claude Code、模型提供方或 API 网关的策略。
