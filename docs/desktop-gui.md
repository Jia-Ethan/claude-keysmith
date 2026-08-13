<!-- markdownlint-disable MD013 -->
# 桌面客户端（GUI）架构与操作手册

`gui/` 是 `claude-keysmith` 的桌面客户端，版本 `0.1.0-beta.1`，构建 channel `beta`，**未签名、未发布**，不是稳定版。它是 CLI（`claude-instruct.py`）的可视化封装：所有文件写入都由 CLI 完成，GUI 自身不直接修改任何目标文件。

- 技术栈：Tauri 2 + React 19 + Vite 6 + Tailwind CSS 4 + Radix UI + Motion；`react-i18next`（zh-CN / en）；`sonner` toast。
- CLI 载体：PyInstaller onefile sidecar（`claude-keysmith-cli`），与 GUI 同源构建。
- 深入规范见 [`../gui/SPEC.md`](../gui/SPEC.md)；JSON 字段见 [`json-contract.md`](json-contract.md)；事务语义见 [`transaction-recovery.md`](transaction-recovery.md)。

## 构建信息

- GUI 版本取自 `gui/package.json`；channel 固定 `beta`。
- `gui/scripts/generate-build-info.mjs` 在 dev/build/test 前运行，把 `git rev-parse HEAD` 注入 `gui/src/lib/build-info.generated.js`（gitignored）；拿不到 git 信息时 commit 记为 `null`、channel 降级为 `development`。commit 只标注构建来源，不代表已发布 tag。
- 前端 `src/lib/buildInfo.js` 只读生成文件，不硬编码任何版本号；缺失字段降级为 `unknown` / `development`。

## 进程边界（`gui/src-tauri/src/cli_runner.rs`）

Rust 侧只负责"找到 CLI、按 argv 数组启动、限时限量收输出"：

- **argv 数组调用**：`Command::new(program).args([...])`，从不做 shell 字符串拼接，无 shell 注入面。
- **sidecar 优先**：打包产物优先使用与主程序同目录的 `claude-keysmith-cli`（PyInstaller onefile）；其后依次尝试 `CLAUDE_KEYSMITH_CLI` 环境变量、主程序目录与若干用户目录 / PATH 中的 `claude-keysmith` / `claude-instruct.py` 回退。`.py` 脚本走 Python 解释器（`CLAUDE_KEYSMITH_PYTHON` 可覆盖）。
- **2 MiB 输出上限**：stdout/stderr 各自封顶 2 MiB，超限继续排空管道但标记截断，最终以"输出不完整"失败关闭，不会基于截断的 JSON 做决策。
- **超时杀整棵进程树**：默认 30 s（`--version` 探测 15 s；前端写操作 120 s）。Unix：`process_group(0)` 建独立进程组 + `kill(-pid, SIGKILL)`；Windows：`CREATE_NEW_PROCESS_GROUP` + `taskkill /PID <pid> /T /F`。另有 `kill_on_drop(true)` 兜底。
- **UTF-8 lossy** 解码输出；非 UTF-8 字节不致命，但 JSON 解析失败会失败关闭。

前端每次调用都通过 `invoke("cli_run", { args, timeoutMs })`；所有业务调用一律带 `--json`，execute 追加 `--yes`（见 `src/lib/api.js`）。

## 数据层（`gui/src/lib/parser.js`）

- `extractJson` 只取 stdout 中首个完整顶层 JSON 对象，容忍前后噪声；未闭合 = 输出不完整。
- `parseContract`：超时 / 非 JSON / `schema` 与 `claude-keysmith/v1` 不符 ⇒ 抛 `ContractError`（失败关闭）。非零 exit 但 JSON 完整时照常返回，由视图层按 `ok`/`blockers` 展示。
- `gateReport` 是唯一的"能否继续"判定：`exit_code !== 0`、`blockers` 非空、`ok === false` 任一成立即 blocked。
- `deriveHealth` 从 status 视图模型推导健康态：`healthy` / `partial-install` / `upgrade-required` / `drifted` / `recovery-required` / `conflict` / `not-installed`（`recovery-required` 优先级最高）。
- 参数构造（`buildInstallArgs` 等）只产出字符串数组，交给 Rust argv 边界。

## 状态与生命周期

- **单实例**：`tauri-plugin-single-instance`，二次启动聚焦已有窗口。
- **全局写互斥**：`src/lib/store.js` 的操作租约（operation lease）；`beginExclusiveOperation` 保证写操作全局唯一，退出排队中拒绝新操作。
- **关闭屏障**：`windowLifecycle.js` 拦截 `onCloseRequested`，有活动操作时排队退出（queued close），空闲后销毁窗口；无托盘（no tray），关了就是退出。
- **窗口**：1200×800，最小 900×600（`tauri.conf.json`）；CSP 收紧到 `default-src 'self'` + IPC，无远程资源。
- **设置持久化**：`localStorage`（`src/lib/settings.js`）：CLI 路径覆盖、默认项目目录、最近项目（仅用户显式选择过的，最多 12 条，**永不扫描磁盘**）、语言、主题。

## 页面与数据来源

| 页面 | 数据来源 | 主要状态 |
|---|---|---|
| Dashboard | `status --scope user --runtime --json` + `doctor --json` | presence / alignment 卡片、source 指纹、runtime readiness、recovery 状态、健康 pill |
| Deploy（3 步向导） | 第 1 步表单（scope/name/源文件/runtime/append/max-tokens）→ 第 2 步 `install --json` preview → 第 3 步确认后 `install --json --yes` | 表单校验失败、preview gate blocked、execute 结果、reload 提示 |
| Manage | `status --json` + `backups --json`（选定 scope） | uninstall / recover / restore / repair 统一走 `preview → ConfirmDialog → execute`；restore 仅从 `backups --json` 的受控备份中选择 |
| Settings | `resolveCli`（sidecar 探测 / 手动路径 + `cli_version`）、localStorage 设置、build info | CLI 检测结果（path/version/runtime）、最近项目管理、语言/主题 |

所有写操作 UI 都先渲染 preview 报告（`ReportView`：actions/backups/warnings/blockers），`gateReport` 通过才允许点确认执行。

## 视觉识别

暖陶土（terracotta）+ 米色纸面 + 炭黑，与 codex-keysmith 的蓝紫色系明确区分：

- Light：accent `#d97757`（hover `#c6613f`），纸面底 `#faf9f5`。
- Dark：暖炭底 `#161311`，accent `#e08a67`（hover `#eea27f`）。
- muted 文本两主题对比度 ≥ 4.5:1（`--text-muted` 有注释标注）。
- 玻璃卡片（`backdrop-filter` 模糊 + 24px 点阵纹理）+ 三团环境光晕缓慢漂移（`AmbientBg`，`prefers-reduced-motion` 下静止）。

## 构建 / 运行 / 验证

```bash
cd gui
npm install
npm test                               # vitest：parser/store/windowLifecycle/视图逻辑
npm run dev                            # vite dev server（纯前端预览）
npm run tauri dev                      # Tauri 开发窗口
npm run build                          # vite 生产构建 → dist/
npm run build:sidecar                  # PyInstaller onefile sidecar（仅本机原生目标）
cd src-tauri && cargo fmt --check && cargo check --locked && cargo test --locked
```

sidecar 构建约定（`scripts/build-sidecar.mjs`）：

- 只支持本机原生构建：`aarch64-apple-darwin` 或 `x86_64-pc-windows-msvc`，跨平台交叉构建直接报错。
- 打包前断言 `claude-instruct.py` 内建 frozen 感知的 `_resource_base()`（frozen 时解析到 `sys._MEIPASS`），缺失则拒绝打包；`examples/` 通过 `--add-data` 进入 `sys._MEIPASS`。
- 构建产物复制为 `src-tauri/binaries/claude-keysmith-cli-<target-triple>[.exe]`，随后立刻执行 `--version` smoke，失败即构建失败。
- Python 环境：激活的 venv 中 `pip install -r gui/requirements-build.txt`，或用 `PYTHON=/path/to/python` 指定。

打包（`npm run bundle` / `tauri build`）在 worktree 之外执行；产物矩阵与验收状态见 [`platform-support.md`](platform-support.md) 与 [`beta-acceptance.md`](beta-acceptance.md)。
