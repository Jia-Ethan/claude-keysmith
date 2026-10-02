# Optional Claude Code mod backend

[中文](mods.md)

This is a community plugin using the official mods API, not an Anthropic plugin.
It requires **Claude Code 2.1.287 or later**. The Python CLI, desktop client and
their defaults remain unchanged. The plugin has its own initial version, 0.1.0.

Migrate legacy deployments before enabling the mod in a new session; avoid combining the two injection paths.

## Load and configure

Inspect the two files in `examples/` before enabling the plugin. From a source
checkout, load the repository root for one session:

```bash
claude --version
claude --plugin-dir /absolute/path/to/claude-keysmith
# In the new session:
/keysmith-status
```

Persistent installation, after this change is available on upstream `main`:

```bash
claude plugin marketplace add Jia-Ethan/claude-keysmith
claude plugin install keysmith@keysmith-mods
```

The plugin is named **`keysmith`**: Claude Code reserves the `claude-` prefix for
first-party plugins. The repository and legacy CLI keep `claude-keysmith`.

Use `/plugin configure keysmith@keysmith-mods` (or the plugin options in `/config`),
then start a new session. Alternatively,
merge the following entry into the appropriate Claude Code settings file. Keep
unrelated settings. For `--plugin-dir`, use the key `keysmith@inline`; for a
marketplace installation use `keysmith@keysmith-mods`.

```json
{
  "pluginConfigs": {
    "keysmith@inline": {
      "options": {
        "mode": "runtime",
        "rulesFile": "",
        "appendFile": "",
        "registerAgent": true
      }
    }
  }
}
```

| Option | Default | Behavior |
|---|---|---|
| `mode` | `runtime` | `runtime` replaces the system prompt; `context` preserves it and adds rules to the first-message context. |
| `rulesFile` | `""` | Read bundled `examples/claude-project-rules.md`; otherwise read the specified absolute local file. |
| `appendFile` | `""` | Read bundled `examples/claude-append-prompt.md`; a custom empty file disables append text. |
| `registerAgent` | `true` | Register `keysmith:keysmith` using the same configured rules and append text. |

Custom paths must be absolute for the machine running Claude Code: `/path/file.md`
on macOS/Linux or `C:\path\file.md` on Windows. Chinese characters and spaces are
supported. Relative paths, `~`, drive-relative paths and network locations are
rejected. Rules must contain a nonempty body; an append file may be empty.

**Runtime is a replacement, not an additive customization.** It intentionally
returns only `keysmith:rules` and, when nonempty, `keysmith:append`, both in session
scope. The first H1 is removed from the rules exactly as in the Python runtime
carrier. Other system-prompt sections are omitted. Other mods and managed tiers
can still change the final answer of the middleware chain.

**Context injects rules only.** Existing context blocks, instruction files and
the default system prompt are preserved. Context never injects append text into
the main conversation. When `registerAgent` is true it still reads the append
file for that separate agent; set it to false for a rules-only deployment that
does not read the append file at all.

The Keysmith agent is registered after session startup, for delegation through
the **Agent tool**. It is not available to the startup `--agent` selector. Ask
Claude to delegate explicitly to `keysmith:keysmith`. This does not replace
the legacy `--agent keysmith` entry or change other agent definitions.

## Migrate existing deployments

The mod performs read-only checks before injecting. It does not install Python,
run the Python CLI, delete files, edit shell profiles, restore settings, or change
permissions. The legacy CLI's JSON contract and fixed `doctor --json` fields are
unchanged.

1. Inventory each existing scope and instruction name, including custom names:

   ```bash
   python3 claude-instruct.py status --scope user --runtime --json
   python3 claude-instruct.py status --scope project --project-dir /path/to/repo --json
   python3 claude-instruct.py status --scope local --project-dir /path/to/repo --json
   ```

2. Save custom rules and append text **outside** the legacy `keysmith/` directory
   before uninstalling. Supply their new absolute paths through plugin options.
   Review pending transaction recovery using the existing CLI before any writes.

3. Preview uninstall for the scope/name actually installed. Add `--runtime` only
   for user runtime deployments and `--agents` only when removing the owned agent.

   ```bash
   python3 claude-instruct.py uninstall --scope user --name YOUR_NAME --runtime --agents
   # After reviewing the preview:
   python3 claude-instruct.py uninstall --scope user --name YOUR_NAME --runtime --agents --yes
   ```

   Use corresponding project/local commands for their import blocks and agents.
   Repeat for each managed name. Backups and journals should be retained.

4. **`uninstall --runtime` leaves `settings.systemPrompt` intact.** If it still
   belongs to Keysmith, remove only that field after checking its ownership, or
   explicitly select an appropriate controlled backup with the existing restore
   workflow. Restoring a whole settings backup can also revert later unrelated
   settings; inspect it first. Do not discard other fields or credentials.

5. Reload the shell/profile, or open a fresh terminal, so a previously loaded
   `claude` function is gone. Remove legacy prompt flags from scripts and aliases.
   Launch a **new** Claude Code session with the plugin and run `/keysmith-status`.

Legacy configuration is not cleaned automatically. Recognized managed imports, wrappers, or matching `settings.systemPrompt` pause new injection. Prompt files or a separate legacy agent alone are reported as residue, not proof of active injection.

Known configured conflicts are conservative: a wrapper on disk blocks injection
even if this launch did not source it. The scan covers the instruction ancestor
walk, user memory, the standard zsh and Documents PowerShell profiles, and an
explicit `CLAUDE_KEYSMITH_SHELL_RC`. Loaded matching legacy instruction files
are also checked by the context hook. Symlinked/imported copies can be recognized
by their loaded text and Keysmith path. Unmarked custom aliases, nonstandard shell
profiles, deleted-but-still-loaded shell functions, and explicit CLI prompt flags
cannot be exhaustively detected. Residue and confirmed configured conflicts are
reported separately; a configuration conflict does not prove active delivery.

## Verification and limits

`/keysmith-status` reports the configured mode, source paths, agent registration,
legacy findings and hook observations. Runtime status also makes a composition
probe and compares the final section IDs **and text** with the expected result.
This proves composition at the time of the probe, not what an earlier request or
an already-snapshotted conversation sent. Context status reports whether its hook
ran; it does not claim that later hooks preserved the context.

Use a new session after configuration changes, cleanup, enable/disable, reload or
updates. Prompt snapshots, resumed conversations and compaction can change when
hooks are rendered. Source files are loaded once per module load; editing Markdown
requires a new session or a plugin reload. A read or conflict-check failure leaves
the original prompt/context intact and skips the optional agent; diagnostics do
not print prompt contents, settings objects, credentials or raw exceptions.

Organization-managed sessions may load the built-in `sec-default` mod, which can
skip user-tier `prompt.compose` and `prompt.context` hooks. A plugin being listed
or an agent being registered does not prove main-session injection. We report
unverified/changed composition and honor the host's policy; there is no fallback
to rewriting `prompt.submit` or weakening permissions. See the
[official sec-default source](https://github.com/anthropics/claude-code/tree/684800b206824dfd0cc8a876e8604b20f72c3617/mods/sec-default).

Disable or uninstall the plugin using Claude Code's plugin commands. A plugin
disabled by `disableAllHooks`, safe mode or host policy cannot run its status
command. Disabling the mod does not restore a conversation's previous prompt
snapshot: verify in a new session.

Only the separately registered Keysmith agent has an explicit copy of the selected
rules and append text. Explore, Plan, custom agents, SDK presets and teammate
prompts have separate composition paths. Test each relevant surface rather than
assuming main-session inheritance. Engineering equivalence of carriers does not
establish equivalent model behavior. Local evidence is recorded in
[mod-acceptance.md](mod-acceptance.en.md).

## Developer checks

```bash
python3 -m pytest -q tests
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate .claude-plugin/marketplace.json --strict
claude plugin test .
python3 tools/test_mod.py
```

`tools/test_mod.py` copies only plugin files, bundled examples, native tests and
LICENSE to temporary directories. It validates both manifests and exercises
runtime, context with/without an agent, and custom paths with Chinese characters
and spaces using the native `claude-code/testing` engine. It needs no credentials
or model calls. Windows CI exercises Windows absolute paths; macOS/Linux exercise
POSIX paths. Local untracked `CLAUDE.md`/`.claude/` are deliberately excluded,
because a root `CLAUDE.md` makes strict plugin validation warn.

CI pins Claude Code **2.1.287** on Linux, macOS and Windows. The runtime hooks do
not require Node.js or Python; these are developer/CLI installation dependencies.
API references: [mods overview](https://code.claude.com/docs/en/plugins/mods/overview),
[mods reference](https://code.claude.com/docs/en/plugins/mods/reference).
