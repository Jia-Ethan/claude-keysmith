<!-- markdownlint-disable MD013 -->
# claude-keysmith GUI — 工程规范（SPEC）

版本 `0.1.0-beta.1`，channel `beta`，未签名，未发布。本规范描述桌面客户端的架构与不可违背的约束；所有条目都能在代码中找到对应实现。发布状态与验收见 [`../docs/platform-support.md`](../docs/platform-support.md) 与 [`../docs/beta-acceptance.md`](../docs/beta-acceptance.md)。

## 1. 定位与边界

GUI 是 `../claude-instruct.py` 的可视化封装，不是重实现：

- **所有**文件写入由 CLI 完成；GUI 不直接读写任何部署目标（memory 文件、keysmith 目录、`settings.json`、shell profile）。
- GUI 只消费 `claude-keysmith/v1` JSON 契约（见 [`../docs/json-contract.md`](../docs/json-contract.md)），不解析人类可读文本输出。
- GUI 只做受控恢复：恢复入口的数据源是 `backups --json` 枚举的 keysmith 受控备份，不提供任意 target/backup 对。

## 2. 技术栈

| 层 | 选型 |
|---|---|
| 壳 | Tauri 2（`tauri.conf.json`，identifier `com.jia-ethan.claude-keysmith-gui`） |
| 前端 | React 19 + Vite 6 + Tailwind CSS 4 + Radix UI + Motion |
| CLI 载体 | PyInstaller onefile sidecar `claude-keysmith-cli`（`scripts/build-sidecar.mjs`） |
| i18n | react-i18next（`zh-CN` / `en`，`src/i18n/`） |
| 反馈 | sonner toast |

## 3. 构建信息

- 版本号唯一来源是 `package.json`；channel 固定 `beta`。
- `scripts/generate-build-info.mjs` 在 dev/build/test 前运行，写入 `src/lib/build-info.generated.js`（gitignored）：`guiVersion`、`channel`、`sourceCommit` / `sidecarCommit`（`git rev-parse HEAD`，40 位 hex 校验）、`generatedAt`。
- commit 只标注构建来源，不代表已发布 tag；拿不到 git 信息时 commit 为 `null`，前端把 channel 降级为 `development`。
- `src/lib/buildInfo.js` 只做归一化与降级（`unknown` / `development`），不硬编码任何版本。

## 4. 进程边界（`src-tauri/src/cli_runner.rs`）

Rust 侧对 CLI 的全部责任：

1. **定位**：sidecar 优先（与主程序同目录的 `claude-keysmith-cli`[`.exe`]）→ `CLAUDE_KEYSMITH_CLI` 环境变量 → 主程序目录 / `~/.claude-keysmith-gui` / `~/claude-keysmith` / `~/.local/bin` / `~/bin` / `/usr/local/bin` / `/opt/homebrew/bin` 中的 `claude-keysmith` / `claude-instruct.py` → PATH。`.py` 走 Python（`CLAUDE_KEYSMITH_PYTHON` 覆盖），runtime 标记为 `bundled` / `executable` / `python`。
2. **启动**：`Command::new(program).args(argv)`——argv 数组，**永不** shell 字符串拼接。`kill_on_drop(true)`。
3. **限量**：stdout/stderr 各 2 MiB 上限；超限继续排空管道（避免子进程阻塞在满管道上），但标记截断并以"输出不完整"失败关闭。
4. **限时**：默认 30 s；`cli_version` 探测 15 s；前端写操作 120 s。超时杀**整棵进程树**：Unix `process_group(0)` + `kill(-pid, SIGKILL)`（覆盖 PyInstaller bootloader 子孙）；Windows `CREATE_NEW_PROCESS_GROUP` + `taskkill /PID <pid> /T /F`。
5. **解码**：UTF-8 lossy。

暴露给前端的 Tauri command：`cli_run` / `detect_cli` / `cli_version` / `cli_runtime`（`src-tauri/src/lib.rs`）。

## 5. 前端数据层

### 5.1 契约解析（`src/lib/parser.js`）

- `extractJson`：只取 stdout 首个完整顶层 JSON 对象（容忍前后噪声；未闭合 = 不完整）。
- `parseContract`：`timed_out` / 非 JSON / `schema !== "claude-keysmith/v1"` ⇒ `ContractError`（失败关闭）。非零 exit 但 JSON 完整时照常返回，交给视图层。
- `gateReport(report)`：**唯一** proceed 判定——`exitCode !== 0`、`blockers.length > 0`、`ok === false` 任一成立即 `{ok: false, reasons}`。
- `deriveHealth(model)`：`recovery-required` > `conflict` > `drifted` > `upgrade-required` > `healthy` / `partial-install` / `not-installed`。
- 视图模型按 operation 分流：`parseWriteReport`（install/uninstall/restore/recover）、`parseStatusReport`、`parseDoctorReport`（固定 9 键）、`parseBackupsReport`。
- 参数构造 `build*Args` 只产出字符串数组。

### 5.2 API 封装（`src/lib/api.js`）

- 每个 invoke 都包在操作租约里（`beginOperation` / `endOperation`）；退出排队中直接 reject。
- 写操作的 execute 阶段走 `cliRunExclusive`（`beginExclusiveOperation`）；preview 与读操作走共享租约。
- 所有业务调用带 `--json`；写操作成对出现：`previewX()`（无 `--yes`）→ `executeX()`（追加 `--yes`，120 s 超时）。
- `resolveCli`：手动路径优先验证（version + runtime），否则走 Rust 侧 sidecar 优先探测。

### 5.3 状态与生命周期（`src/lib/store.js` + `windowLifecycle.js`）

- **全局写互斥**：`beginExclusiveOperation` 原子获取；已有操作或退出排队时返回 `null`。由 `api.js` 的 `cliRunExclusive` 在所有 `execute*` 写路径上实际持有（install / uninstall / restore / recover）；CLI 侧的 `.keysmith.lock` 是第二道跨进程门禁。
- **操作租约**：UI 统一读 `operationInProgress` 作为交互锁；租约未清零拒绝视图切换。
- **关闭屏障**：`onCloseRequested` → `requestExitWhenIdle`；有活动租约时排队（queued close），最后一个租约结束后销毁窗口（`destroy()` 失败回退 `close()`）；销毁期间屏障保持封闭，迟到的 sidecar 不会启动。**无托盘**——关闭即退出。
- **单实例**：`tauri-plugin-single-instance`，二次启动 unminimize + show + focus 主窗口。
- **窗口**：1200×800，最小 900×600，`devtools: false`；CSP `default-src 'self'` + 本地 IPC，无远程资源。

### 5.4 设置持久化（`src/lib/settings.js`）

localStorage 单键 `claude-keysmith-gui:settings`：`cliPath`（留空 = 自动探测）、`defaultProjectDir`、`recentProjects`（**仅用户显式选择过的路径**，去重置顶，上限 12 条，永不扫描磁盘）、`lang`、`theme`。

## 6. 页面

| 页面 | 数据来源 | 关键状态 |
|---|---|---|
| **Dashboard** | `status --scope user --runtime --json`、`doctor --json` | presence / alignment 卡片、source 指纹与 drift、runtime readiness（上游候选、wrapper 是否当前、旧 launcher）、`recovery_state`、健康 pill；`recovery-required` 时引导到 Manage |
| **Deploy**（3 步向导） | 表单（scope / project dir / name / 内置或本地源文件 / runtime / append / max-tokens）→ `install --json` preview → 确认后 `--yes` | 表单校验（name 正则 `^[A-Za-z0-9._-]+$`、max-tokens 正整数）、preview gate、execute 报告、`reload_hint` 提示；成功的 project/local 部署记入最近项目 |
| **Manage** | `status --json` + `backups --json`（选定 scope） | uninstall / recover / restore / repair（runtime 重对齐）统一 `preview → ConfirmDialog → execute`；restore 仅从受控备份列表选择；scope 为 project/local 时要求显式 project dir |
| **Settings** | `resolveCli`、localStorage、build info | CLI 路径覆盖与探测结果（path / version / runtime）、默认项目目录、最近项目管理、语言与主题、版本与 commit 展示 |

报告渲染统一走 `ReportView`（actions / backups / warnings / blockers / reload 提示），原始 JSON 可展开（`RawJson`）。

## 7. 视觉识别

暖陶土 + 米色纸面 + 炭黑（**不是** codex-keysmith 的蓝紫色系）：

| Token | Light | Dark |
|---|---|---|
| `--accent` | `#d97757`（hover `#c6613f`） | `#e08a67`（hover `#eea27f`） |
| `--bg-primary` | `#faf9f5`（米色纸面） | `#161311`（暖炭） |
| brand 渐变 | `#d97757 → #c6613f → #d4a27f` | `#e08a67 → #c9744f → #d4a27f` |

- muted 文本两主题对比度 ≥ 4.5:1（`globals.css` 中有注释标注）。
- 玻璃卡片：`backdrop-filter: blur(16px) saturate(...)` + 24px 点阵纹理 + 内高光。
- 环境层：三团主题色光晕缓慢漂移（`AmbientBg`），`prefers-reduced-motion` 下静止。
- 紧凑层级、状态 pill、toast 反馈保留。

## 8. Sidecar 构建契约（`scripts/build-sidecar.mjs`）

- 仅本机原生构建：`aarch64-apple-darwin` / `x86_64-pc-windows-msvc`；host 与 target 不一致直接报错（PyInstaller onefile 不支持交叉）。
- **frozen 资源断言**：打包前检查 `claude-instruct.py` 含 `def _resource_base()` 且 frozen 时解析 `sys._MEIPASS`，缺失则拒绝打包。`examples/` 以 `--add-data` 进入 `sys._MEIPASS`，frozen 下由 `_resource_base()` 定位，无需源码补丁。
- 构建环境净化：`PYTHONNOUSERSITE=1`，删除 `PYTHONHOME` / `PYTHONPATH` / `PYTHONUSERBASE`；`PYTHON` 环境变量指定解释器（需 `pip install -r requirements-build.txt`）。
- 产物原子落位 `src-tauri/binaries/claude-keysmith-cli-<triple>[.exe]`（先复制到临时名再 rename，Unix 下 `chmod 755`），随后 `--version` smoke，失败即构建失败。
- `npm run bundle` 是唯一打包入口：先构建 sidecar，再加载 `tauri.bundle.conf.json` 启用 bundle 并声明 `externalBin`。常驻配置 `bundle.active=false`，裸 `tauri build` 只产 executable；即使显式传 `--bundles`，默认 `beforeBundleCommand` 也会拒绝。overlay 覆盖该 hook 后仍按 `TAURI_ENV_TARGET_TRIPLE` 校验目标 sidecar 存在且可执行。
- macOS 目标由 `tauri.macos.conf.json` 声明 `app` + `dmg`；Windows 由 `tauri.windows.conf.json` 声明 NSIS currentUser + WebView2 downloadBootstrapper。Windows 原生 CI 已覆盖构建、静默安装/卸载、冻结 sidecar、PowerShell wrapper、restore/recover、隐私、GUI 进程与单实例，并在 source CLI 层覆盖旧 launcher 迁移/强杀恢复；实体机可见 UI、SmartScreen、无 WebView2 与事务强杀恢复状态见发布验收文档。

## 9. 不变量（改动必须保持）

1. GUI 不写部署目标文件；一切写入经 CLI `--yes`。
2. argv 数组边界，无 shell 拼接。
3. 截断 / 超时 / 非契约 JSON 一律失败关闭。
4. `gateReport` 是唯一的 proceed 判定。
5. 恢复只用 `backups --json` 的受控备份。
6. 无网络、无遥测、无凭证接触（见 [`../docs/privacy-security.md`](../docs/privacy-security.md)）。
7. 单实例、写互斥、关闭屏障、无托盘。
8. 版本与 channel 不写死；构建信息只来自 `generate-build-info.mjs`。
