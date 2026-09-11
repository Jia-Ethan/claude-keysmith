<!-- markdownlint-disable MD013 MD033 MD041 -->

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/claude-keysmith-hero-dark.webp" />
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/claude-keysmith-hero-light.webp" />
  <img src="docs/assets/readme/claude-keysmith-hero-light.webp" alt="claude-keysmith" width="100%" />
</picture>

<p>
  <a href="https://github.com/Jia-Ethan/claude-keysmith/stargazers"><img src="https://img.shields.io/github/stars/Jia-Ethan/claude-keysmith?style=flat-square&color=%232f81f7" alt="GitHub Stars" /></a>
  <a href="https://github.com/Jia-Ethan/claude-keysmith/releases/latest"><img src="https://img.shields.io/badge/Stable-v7.2-2f81f7?style=flat-square" alt="Stable v7.2" /></a>
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.8+" />
  <img src="https://img.shields.io/badge/license-MIT-6DB33F?style=flat-square" alt="MIT License" />
</p>

<p>
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">使用说明</a> ·
  <a href="LICENSE">License</a>
</p>

<h1>claude-keysmith</h1>

<p>给 Claude Code 装上一份可撤销的指令。先看计划，确认了再写入。</p>

</div>

## 简体中文

Keysmith 给本机的 AI 编程工具装指令：先预览，再写入，能验证，能撤走。

`claude-keysmith` 面向 **Claude Code**。装上之后，新开的对话会按这份指令工作。不改 Claude Code 软件本身，也不读取账号和密钥。

> [!IMPORTANT]
> 这会改变 Claude Code **之后新开的对话**。默认只给你看计划，加上确认才会写入。装完后请开一个新会话。

## 使用方式

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/project-architecture-zh-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/project-architecture-zh-light.webp" />
    <img alt="先看计划，确认后装上，新对话生效，随时可以撤走" src="docs/assets/readme/project-architecture-zh-light.webp" width="100%" />
  </picture>
</p>

1. **先看计划。** 确认之前什么都不会写入。
2. **确认后装上。** 指令交给本机 Claude Code，软件保持原样。
3. **新开一轮对话。** 新会话才会生效。
4. **随时撤走。** 同样先看计划，确认后恢复成原来的样子。

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/claude-keysmith-preview-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/claude-keysmith-preview-light.webp" />
    <img src="docs/assets/readme/claude-keysmith-preview-light.webp" alt="示意预览；实际路径与输出以本机 dry-run 为准" width="100%" />
  </picture>
</p>

## 选哪个 Keysmith

| 你在用 | 用这个 | 怎么开始 |
| --- | --- | --- |
| [Codex](https://github.com/Jia-Ethan/codex-keysmith) | codex-keysmith | 稳定版安装包 |
| **Claude Code** | **claude-keysmith** | 源码 |
| [Grok Build](https://github.com/Jia-Ethan/grok-keysmith) | grok-keysmith | 稳定版安装包 |
| [ZCode](https://github.com/Jia-Ethan/zcode-keysmith) | zcode-keysmith | 源码 |

每个工具一份安装器。选你正在用的即可。也有桌面版（未签名）。

## 效果

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/results-zh-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/results-zh-light.webp" />
    <img alt="同一批 4 题，完整交出产物从 1 题到 3 题" src="docs/assets/readme/results-zh-light.webp" width="92%" />
  </picture>
</p>

同一模型、同一批 4 道题，完整交出产物的题数从 1 题到 3 题。

## 开始使用

本机需要已经装好 Claude Code。目前以源码安装为主。

```bash
git clone --branch v7.2 --depth 1 https://github.com/Jia-Ethan/claude-keysmith.git
cd claude-keysmith
python3 claude-instruct.py install --scope project --project-dir .
python3 claude-instruct.py install --scope project --project-dir . --yes
```

装完后开一个新的 Claude Code 会话。也可以把 [代装说明](docs/agent-install.md) 交给你正在用的 AI 助手。细节见 [使用说明](docs/reference.md)。

## 怎么撤走

```bash
python3 claude-instruct.py uninstall --scope project --project-dir .
python3 claude-instruct.py uninstall --scope project --project-dir . --yes
```

先看计划，确认后再恢复。

## 适用环境

macOS、Windows 与 Linux。需要 Python 3.8+。

## 文档

- [使用说明](docs/reference.md)
- [代装说明](docs/agent-install.md)
- [隐私与安全](docs/privacy-security.md)

## 系列

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — 给 Codex
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — 给 Claude Code
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — 给 Grok Build
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — 给 ZCode

官方反馈：[GitHub Discussions](https://github.com/Jia-Ethan/claude-keysmith/discussions/13) · 社区：[LINUX DO](https://linux.do)

## Star History

<p align="center">
  <a href="https://star-history.com/#Jia-Ethan/claude-keysmith&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Jia-Ethan/claude-keysmith&type=Date&theme=dark">
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Jia-Ethan/claude-keysmith&type=Date">
    </picture>
  </a>
</p>
