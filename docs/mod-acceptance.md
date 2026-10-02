# Mod backend acceptance evidence

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

The startup command `--agent keysmith:keysmith` failed with “not found”, because
dynamic registration runs after startup agent selection. Use Agent-tool
delegation, as documented in [mods.md](mods.md); the legacy agent carrier remains
available for its original startup use case.

## Limits

This is a small carrier smoke test, not a benchmark or proof that model behavior
matches the published Keysmith results. It confirms actual injection of custom
text in the tested main session and separately registered agent. It does **not**
establish universal inheritance: Explore and Plan did not show those markers.
No SDK, Desktop/VS Code, teammate, resumed-session or real organization-policy
acceptance is claimed. New sessions are required when evaluating enable/disable
or changed prompt configuration.
