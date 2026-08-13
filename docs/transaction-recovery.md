<!-- markdownlint-disable MD013 -->
# 事务与恢复层：durable journal + write lock

`claude-instruct.py` 的所有写路径（`install` / `uninstall` / 受控 `restore`）在 scope 本地持有一个 keysmith 专属的持久化事务日志（journal）和排他写锁。目标是：中断（崩溃、Ctrl+C、断电）后磁盘上永远存在足够证据，把未提交的事务回滚到之前的状态，或核验已提交的事务无须回滚。整个机制失败关闭（fail-closed）：证据不足时宁可阻塞后续写入，也不猜测。

## 文件位置

每个 scope 的 keysmith 目录同时是锁目录与 journal 目录：

| Scope | keysmith 目录 |
|---|---|
| `user` | `~/.claude/keysmith/` |
| `project` / `local` | `<repo>/.claude/keysmith/` |

| 文件 | 作用 |
|---|---|
| `.keysmith.lock` | 排他写锁，O_EXCL 创建，内容为 `{schema, pid, label, acquired_at}` |
| `.journal-<uuid>.json` | 单个事务的持久化日志（`schema: "claude-keysmith-journal/v1"`） |

锁和 journal 都在 scope 本地，互不干扰；同一 scope 同一时刻只允许一个写事务。

## 写锁（`.keysmith.lock`）

- 通过 `os.O_WRONLY | os.O_CREAT | os.O_EXCL` 原子创建；已存在即读持有者元数据。
- **持有者存活**（PID 可探测，Windows 用 `tasklist` 探测，POSIX 用 `kill(pid, 0)`）⇒ 抛 `TransactionConflict`，当前写入失败关闭，不排队、不抢占。
- **持有者已死或元数据不可读** ⇒ 锁被回收（删除后重建），并标记 `reclaimed_stale`：新持有者在写入前必须先做一次完整的残留扫描（见下文写入门槛），因为上一个持有者可能死在事务中途。
- 锁随 `finally` 释放；进程异常退出留下的锁按"持有者已死"路径被下一次写入或 `recover` 回收。

## Journal 生命周期

journal 在每次真实写入前创建，**每个 mutation 前后都原子落盘**（先写临时文件再 rename），保证崩溃瞬间磁盘上总有完整记录：

```
创建 (state=pending)
  → log_step(before 指纹) → 执行 mutation → log_step(after 指纹)   （每步重复）
  → commit (state=committed)
  → finish（无残留则删除 journal 文件）
```

记录内容：`journal_id`（uuid hex）、`operation`、`scope`、`scope_root`、`pid`、`started_at`/`committed_at`、`state`，以及：

- `steps[]`：每步 `{action: backup|write|remove|migrate, path, before: {sha256,size_bytes,exists}, after: {...}, backup_path?, at}`；`migrate` 步骤额外记录 `moved: [[source, backup], ...]`（Windows 旧 launcher 迁移）。
- `backups[]`：备份证据 `{target, backup_path, sha256, size_bytes, created}`。

两阶段语义：

- **commit 成功前中断（state=pending）** ⇒ 下次写入或 `recover` 时**逆序回滚**：文件当前指纹匹配 after ⇒ 用备份/旧内容恢复 before 状态；before 不存在（事务新建文件）⇒ 删除；当前指纹仍等于 before（写入未生效）⇒ 跳过。`migrate` 步骤逆序把备份 rename 回原路径。
- **commit 成功后中断（state=committed）** ⇒ **永不反转**。只做残留核验（例如已提交迁移的目标被意外重建则报告 blocker），核验干净后消费掉 journal。这就是"crash-after-commit 窗口"：`journal.finish()` 删除失败或进程死在 commit 与 finish 之间时，下一次写入会在锁内核验该 committed journal 无残留后直接消费，不阻塞。

回滚定位 before 内容的顺序：优先使用步骤记录的 `backup_path`（校验其 sha256 等于 before）；缺失时在同目录的 `<name>.bak_*` 候选中找指纹匹配者；都找不到 ⇒ blocker，保留证据。

## 写入门槛（fail-closed gate）

任何写命令（含 `recover --yes` 自身之外的 `install` / `uninstall` / 受控 `restore`）在执行阶段、持锁之后，先运行 `_blockers_for_recovery_residue`：

1. 存在 **pending** journal ⇒ 阻塞，提示先运行 `recover`。
2. 存在 **committed** journal ⇒ 现场核验；有残留 ⇒ 阻塞；无残留 ⇒ 消费 journal 后继续。
3. journal 无法解析（损坏）⇒ 阻塞，证据原样保留，不做任何修复尝试。
4. 刚回收的失效锁 ⇒ 在锁内重复一次完整扫描（防并发写者）。
5. user scope `settings.json` 存在 `"claude-keysmith recovery marker"` 键 ⇒ 阻塞（`systemPrompt` 回滚待确认）。唯一例外：受控恢复 user scope `settings.json` 本身就是该标记的修复手段，会过滤掉这一条 blocker（其余 blocker 仍然生效）。

preview 模式（无 `--yes`）完全不触碰文件系统，不检查门槛、不取锁。

## 失败关闭条件汇总

出现以下任一情况，操作以 blocker 终止并保留全部证据：

- 回滚目标已存在（`restore-moved` 目标路径被重建），拒绝覆盖。
- 当前文件指纹既不等于 before 也不等于 after ⇒ "未知修改"，拒绝回滚。
- `remove` 步骤的目标被未知方重建（存在但指纹不等于 before）⇒ 拒绝覆盖。
- 找不到匹配 before 指纹的备份 ⇒ 回滚受阻。
- 迁移备份缺失 ⇒ 无法回滚该迁移。
- 未知的 journal 步骤类型 ⇒ 保留证据并阻塞。
- 活跃的他方锁（live PID）。
- 损坏的 journal ⇒ 保留证据并阻塞。
- 已提交事务的迁移目标被重建 ⇒ 保留并报告。

## `recover` 用法

```bash
# 预览：列出 residue 与 planned_repairs，不修改任何文件
python3 claude-instruct.py recover --scope user --json

# 执行恢复（幂等；无残留时是干净的 no-op）
python3 claude-instruct.py recover --scope user --yes --json
```

执行阶段行为：

1. 失效锁：报告 `reclaim-lock` 动作，由随后的 `ScopeWriteLock` 获取自然回收；活跃锁 ⇒ blocker，拒绝在写入进行中恢复。
2. pending journal ⇒ 逆序回滚（见上）；全部步骤干净后删除 journal（`cleanup-journal`）。
3. committed journal ⇒ 核验残留，干净则删除 journal。
4. settings 恢复标记存在且没有其它 blocker ⇒ 校验 `settings.systemPrompt` 与 `~/.claude/keysmith/system-prompt.md` 一致后清除标记；不一致 ⇒ blocker，提示先用 `backups` 选受控备份执行 `restore` 再运行 `recover`。
5. 任一 journal 有 blocker ⇒ 该 journal 与证据保留，整体 `ok: false`、`exit_status: 1`。

## runtime uninstall 与 settings 语义

`uninstall --runtime` 移除 `system-prompt.md`、`append-prompt.md` 和 managed shell wrapper（各自先备份），但**从不自动回滚 `settings.systemPrompt`**——避免覆盖安装后由用户或其他工具写入的配置。回滚 `systemPrompt` 的唯一路径是显式的受控备份恢复：

```bash
python3 claude-instruct.py backups --scope user --json          # 找到 settings.json.bak_* 备份
python3 claude-instruct.py restore \
  --target ~/.claude/settings.json \
  --backup ~/.claude/settings.json.bak_YYYYMMDD_HHMMSS_pre_runtime \
  --yes
```

受控恢复（`managed: true`，即备份名匹配 `<target>.bak_*` 且与目标同目录）走 journal/lock；恢复前会再为当前 `settings.json` 生成 `*_pre_restore` 安全备份。GUI 只暴露这条受控路径，不提供任意 target/backup 对的自由恢复。

## 与 GUI 的关系

- GUI 的每次写操作都是 `preview（无 --yes）→ 用户确认 → execute（--yes）` 两步；preview 无副作用。
- `status --json` 的 `recovery_state` 块把 journal/锁状态直接暴露给 GUI：`recovery_required` 或 `must_recover_before_writes` 为 `true` 时，GUI 健康状态为 `recovery-required`，写操作入口被禁用并引导到 Manage 页执行 `recover`。
- 锁是 CLI 进程级的第二道防线；GUI 自身还有前端操作租约（`store.js`）防止应用内并发写，两道互不影响。
