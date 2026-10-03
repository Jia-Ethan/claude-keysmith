# Mod backend acceptance evidence

[中文](mod-acceptance.md)

Recorded **2026-10-02**, against upstream `b3d8cc2`, using Claude Code **2.1.287**
on macOS. Tests used a temporary plugin copy, a fresh workspace/config directory,
the locally configured model provider, and harmless custom Markdown. No production
deployment or user configuration cleanup was performed.

## Automated checks

- Existing Python suite: **155 passed**.
- Native hooks: **21 cases × 4 manifest variants = 84 passed** using
  `python3 tools/test_mod.py`. Runtime bundled, context with/without agent, and
  custom absolute files with Chinese characters and spaces were exercised.
- Each variant passed strict validation of both plugin and marketplace manifests.
- Supplementary strict TypeScript checking passed against Anthropic's published
  declarations at `684800b206824dfd0cc8a876e8604b20f72c3617` (whose generated-file
  header names 2.1.277). The native 2.1.287 validator/tests and live sessions,
  rather than that older header, establish the target runtime compatibility.
- Native policy fixtures exercised managed-tier prompt bypass and plugin refusal.
  They do not stand in for an actual Team/Enterprise organization account.
- The CI workflow pins 2.1.287 on Linux, macOS and Windows. Local execution alone
  does not establish Windows filesystem or PowerShell compatibility; Windows CI
  uses a Windows absolute custom-file path.

## Real sessions

Rules file:

```markdown
# Smoke rules

For this smoke test, begin each answer with KEYSMITH_RULE_MARKER.
```

Append file:

```text
After the beginning marker, include KEYSMITH_APPEND_MARKER before the deliverable.
```

Task: `Return a Python function add(a, b) that returns their sum. Output the function only.`

| New session | Observation |
|---|---|
| `claude -p`, mod runtime | Both markers followed by a working `return a + b` function. |
| `claude -p`, legacy `--system-prompt-file` + `--append-system-prompt-file` | Both markers followed by the same function; formatting differed slightly. |
| `claude -p`, mod context | Rules marker and function, without the append marker. |
| `claude -p`, mod disabled using `disableAllHooks: true` | Function without either marker. |
| Interactive terminal, runtime | `/keysmith-status` verified composition; the task returned both markers and the function. |
| Agent-tool delegation to `keysmith:keysmith` | Recorded an actual Agent call with this type; the child tool result included both markers and the function. |
| Agent-tool delegation to `Explore` | Actual child tool result contained the function without the Keysmith markers. |
| Agent-tool delegation to `Plan` | Actual child tool result contained the function and planning prose without the Keysmith markers. |

For headless model calls, tool availability was limited to either no tools or the
Agent tool, permission mode was `dontAsk`, and each call had a budget/turn limit.
Agent observations above refer to the **child's tool result**, not the parent's
final answer: the parent continued to use its own Keysmith markers.

`/keysmith-status` was also run headlessly with plugin options supplied through
`pluginConfigs["keysmith@inline"].options`. It reported the selected custom files,
registered agent, and verified the final composition's IDs, text and scope.

A local marketplace was added and `keysmith@keysmith-mods` installed into the
temporary config directory. A new headless session without `--plugin-dir`, with
options keyed by `keysmith@keysmith-mods`, successfully ran `/keysmith-status`
and verified composition. The user's actual plugin installation was untouched.

The startup command `--agent keysmith:keysmith` failed with “not found”, because
dynamic registration runs after startup agent selection. Use Agent-tool
delegation, as documented in [mods.md](mods.en.md); the legacy agent carrier remains
available for its original startup use case.

## Limits

This is a small carrier smoke test, not a benchmark or proof that model behavior
matches the published Keysmith results. It confirms actual injection of custom
text in the tested main session and separately registered agent. It does **not**
establish universal inheritance: Explore and Plan did not show those markers.
The live model tests used custom Markdown; systematic evaluation of the full bundled prompts has not been performed.
No SDK, Desktop/VS Code, teammate, resumed-session or real organization-policy
acceptance is claimed. New sessions are required when evaluating enable/disable
or changed prompt configuration.
