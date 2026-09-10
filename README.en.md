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
  <a href="README.md">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="docs/reference.md">Guide</a> ·
  <a href="LICENSE">License</a>
</p>

<h1>claude-keysmith</h1>

<p>Install a reversible instruction onto Claude Code. Preview first, write only after you confirm.</p>

</div>

## English

Keysmith installs instructions onto local AI coding tools: preview, apply, verify, and undo.

`claude-keysmith` is the installer for **Claude Code**. After it is on, new conversations follow the instruction. The app itself is not modified, and accounts and keys are never read.

> [!IMPORTANT]
> This changes **later new conversations** in Claude Code. Commands show the plan first and write only when you confirm. Open a new session after installing.

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/project-architecture-en-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/project-architecture-en-light.webp" />
    <img alt="Preview the plan, apply when ready, new chats pick it up, remove it whenever you want" src="docs/assets/readme/project-architecture-en-light.webp" width="100%" />
  </picture>
</p>

1. **Preview first.** Nothing is written until you confirm.
2. **Apply when ready.** The instruction is installed locally. The app stays official.
3. **Start a new conversation.** A fresh session is required.
4. **Remove it whenever you want.** Review the plan, then restore how it was.

## Which Keysmith to use

| You use | Installer | How to start |
| --- | --- | --- |
| [Codex](https://github.com/Jia-Ethan/codex-keysmith) | codex-keysmith | Stable package |
| **Claude Code** | **claude-keysmith** | Source |
| [Grok Build](https://github.com/Jia-Ethan/grok-keysmith) | grok-keysmith | Stable package |
| [ZCode](https://github.com/Jia-Ethan/zcode-keysmith) | zcode-keysmith | Source |

One installer per tool. An unsigned desktop build is also available.

## Results

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/results-en-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/results-en-light.svg" />
    <img alt="On the same 4 prompts, complete artifacts rose from 1 to 3" src="docs/assets/readme/results-en-light.svg" width="92%" />
  </picture>
</p>

On the same model and the same 4 prompts, complete artifacts rose from 1 to 3.

## Get started

Claude Code must already be installed. Source install is the conservative path.

```bash
git clone --branch v7.2 --depth 1 https://github.com/Jia-Ethan/claude-keysmith.git
cd claude-keysmith
python3 claude-instruct.py install --scope project --project-dir .
python3 claude-instruct.py install --scope project --project-dir . --yes
```

Then open a new Claude Code session. You can also hand the [agent-install notes](docs/agent-install.md) to an AI assistant. Details live in the [guide](docs/reference.md).

## Undo

```bash
python3 claude-instruct.py uninstall --scope project --project-dir .
python3 claude-instruct.py uninstall --scope project --project-dir . --yes
```

Review the plan, then confirm.

## Platform

macOS, Windows, and Linux. Python 3.8+.

## Docs

- [Guide](docs/reference.md)
- [Agent install](docs/agent-install.md)
- [Privacy](docs/privacy-security.md)

## Series

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — for Codex
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — for Claude Code
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — for Grok Build
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — for ZCode

Feedback: [GitHub Discussions](https://github.com/Jia-Ethan/claude-keysmith/discussions/13) · Community: [LINUX DO](https://linux.do)

## Star History

<p align="center">
  <a href="https://star-history.com/#Jia-Ethan/claude-keysmith&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Jia-Ethan/claude-keysmith&type=Date&theme=dark">
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Jia-Ethan/claude-keysmith&type=Date">
    </picture>
  </a>
</p>
