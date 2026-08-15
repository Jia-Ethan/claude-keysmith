<!-- markdownlint-disable MD013 -->
# Release Notes 草稿（双 Pre-release）

发布方式：`v7` 与 `desktop-v0.1.0-beta.1` 同批标记为 **Pre-release**，两者指向同一个最终 main commit。

## v7

### v7：事务恢复与运行时稳定性（预发布）

claude-keysmith v7 预发布版，集中验证自动化契约、写入安全和 Claude Code 更新后的运行时稳定性。

升级 runtime wrapper：

```bash
python3 claude-instruct.py install --scope user --runtime
python3 claude-instruct.py install --scope user --runtime --yes
```

## desktop-v0.1.0-beta.1

### Desktop 0.1.0-beta.1：未签名桌面客户端 beta

首个 claude-keysmith 桌面客户端 beta，内嵌与 v7 同源构建的 CLI。

- 提供 Dashboard、三步 Deploy、Manage（uninstall / restore / recover / repair）和中英文 Settings。
- 所有写操作都经过 preview → confirm → execute，并具备全局写互斥、关闭等待、超时杀进程树和事务恢复。
- 支持 macOS Apple Silicon 与 Windows x64；无 Linux GUI、无自动更新。

产物：

- `claude-keysmith-desktop-0.1.0-beta.1-macos-arm64-unsigned.dmg`
- `claude-keysmith-desktop-0.1.0-beta.1-windows-x64-unsigned-setup.exe`
- `SHA256SUMS`

最终 SHA-256 以精确 main 候选生成后的校验清单为准。
