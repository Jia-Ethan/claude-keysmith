import type { EngineInterface, Register } from 'claude-code'
import {
  AGENT_DESCRIPTION,
  type Options, agentBody, contextOf, isLegacyImport, optionsOf, sectionsOf, systemBody,
} from './prompts'

type Loaded = { rules: string; append: string; rulesPath: string; appendPath: string | null }
type Finding = { kind: 'conflict' | 'residue'; detail: string }

type State = {
  loaded?: Loaded
  pending?: Promise<void>
  error?: string
  findings: Finding[]
  contextObserved: boolean
  composeObserved: boolean
  registeredAgent: boolean
  told: Set<string>
}

function add(state: State, kind: Finding['kind'], detail: string) {
  if (!state.findings.some(item => item.kind === kind && item.detail === detail)) state.findings.push({ kind, detail })
}

function tell($: EngineInterface, state: State, message: string) {
  if (!state.told.has(message)) {
    state.told.add(message)
    $.ui.log(message)
  }
}

function blocked(state: State) { return !!state.error || state.findings.some(item => item.kind === 'conflict') }

async function readExisting($: EngineInterface, path: string): Promise<string | undefined> {
  return await $.fs.exists(path) ? $.fs.read(path) : undefined
}

async function inspectLegacy($: EngineInterface, state: State, prompts: Loaded) {
  // Only inspect the systemPrompt field; never log settings or arbitrary errors.
  const settings = await $.settings.read()
  const configuredPrompt = settings.systemPrompt
  if (typeof configuredPrompt === 'string' && configuredPrompt.trim() &&
      configuredPrompt.trim() === systemBody(prompts.rules).trim()) {
    add(state, 'conflict', 'settings.systemPrompt matches Keysmith rules')
  }
  const home = await $.env.get('CLAUDE_KEYSMITH_HOME') ||
    await $.env.get('HOME') || await $.env.get('USERPROFILE')
  const configDir = await $.env.get('CLAUDE_CONFIG_DIR') || (home ? `${home}/.claude` : undefined)
  if (configDir) {
    const oldSystem = await readExisting($, `${configDir}/keysmith/system-prompt.md`)
    const oldAppend = await $.fs.exists(`${configDir}/keysmith/append-prompt.md`)
    if (oldSystem !== undefined || oldAppend) add(state, 'residue', 'Legacy runtime prompt files exist')
    if (oldSystem?.trim() && typeof configuredPrompt === 'string' &&
        configuredPrompt.trim() === oldSystem.trim()) {
      add(state, 'conflict', 'settings.systemPrompt matches the deployed legacy runtime file')
    }
    const memory = await readExisting($, `${configDir}/CLAUDE.md`)
    if (memory?.includes('<!-- claude-keysmith:start name=')) {
      add(state, 'conflict', 'Managed Keysmith import configured in user CLAUDE.md')
    }
    const agent = await readExisting($, `${configDir}/agents/keysmith.md`)
    if (agent?.includes('<!-- claude-keysmith:start name=keysmith-agent -->')) {
      add(state, 'residue', 'Legacy user Keysmith agent exists (a separate agent type)')
    }
  }
  const ancestors = await $.fs.ancestors({
    names: ['CLAUDE.md', 'CLAUDE.local.md', '.claude/CLAUDE.md', '.claude/agents/keysmith.md'],
  })
  for (const file of ancestors) {
    const raw = await readExisting($, `${file.dir}/${file.name}`)
    if (file.name.endsWith('agents/keysmith.md')) {
      if (raw?.includes('<!-- claude-keysmith:start name=keysmith-agent -->') ||
          file.content.includes('<!-- claude-keysmith:start name=keysmith-agent -->')) {
        add(state, 'residue', 'Legacy project Keysmith agent exists (a separate agent type)')
      }
    } else {
      // ancestors() strips comments. Read the memory file itself for ownership
      // markers, including imports whose deployed rules differ from these rules.
      if (file.parts.some(part => isLegacyImport(part.path, part.content, prompts.rules)) ||
          raw?.includes('<!-- claude-keysmith:start name=') ||
          file.content.includes('<!-- claude-keysmith:start name=')) {
        add(state, 'conflict', 'Managed Keysmith import configured on the project instruction walk')
      }
    }
  }
  const explicitProfile = await $.env.get('CLAUDE_KEYSMITH_SHELL_RC')
  const profiles = explicitProfile ? [explicitProfile] : home ? [
    `${home}/.zshrc`,
    `${home}/Documents/PowerShell/Microsoft.PowerShell_profile.ps1`,
    `${home}/Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1`,
  ] : []
  for (const profile of profiles) {
    const text = await readExisting($, profile)
    if (text?.includes('# >>> claude-keysmith runtime >>>') &&
        text.includes('# <<< claude-keysmith runtime <<<')) {
      add(state, 'conflict', 'Managed Keysmith shell wrapper configured; unload it before using the mod')
    }
  }
}

async function ensureLoaded($: EngineInterface, state: State, options: Options) {
  state.pending ??= (async () => {
    try {
      const rulesPath = options.rulesFile || `${$.plugin.root}/examples/claude-project-rules.md`
      // Context itself never needs append text. The optional agent does.
      const appendPath = options.mode === 'runtime' || options.registerAgent
        ? options.appendFile || `${$.plugin.root}/examples/claude-append-prompt.md`
        : null
      const windowsHost = /^[A-Za-z]:[\\/]/.test($.plugin.root)
      for (const path of [rulesPath, appendPath]) {
        if (path && /^[A-Za-z]:[\\/]/.test(path) !== windowsHost) {
          throw new Error('Custom prompt path belongs to a different operating system')
        }
      }
      const rules = await $.fs.read(rulesPath)
      const append = appendPath ? await $.fs.read(appendPath) : ''
      if (!systemBody(rules).trim()) throw new Error('Empty rules')
      const prompts = { rules, append, rulesPath, appendPath }
      await inspectLegacy($, state, prompts)
      state.loaded = prompts
    } catch {
      state.error = 'Unable to load prompt files or check legacy configuration; no Keysmith injection applied'
    }
    if (state.error) tell($, state, state.error)
    for (const finding of state.findings) {
      tell($, state, `${finding.kind}: ${finding.detail}. See docs/mods.md and /keysmith-status.`)
    }
  })()
  await state.pending
}

export const register: Register = (on, rawOptions) => {
  const options = optionsOf(rawOptions)
  const state: State = {
    findings: [], contextObserved: false, composeObserved: false,
    registeredAgent: false, told: new Set(),
  }

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'keysmith-status', description: 'Show Keysmith mod sources, conflicts and prompt verification',
    })
    await ensureLoaded($, state, options)
    if (options.registerAgent && state.loaded && !blocked(state)) {
      try {
        await $.agent.register({
          name: 'keysmith', description: AGENT_DESCRIPTION,
          prompt: agentBody(state.loaded.rules, state.loaded.append),
        })
        state.registeredAgent = true
      } catch {
        tell($, state, 'Keysmith agent registration failed; /keysmith-status reports it separately')
      }
    }
    return next(e)
  })

  on('prompt.context', async ($, e, next) => {
    await ensureLoaded($, state, options)
    for (const file of e.instructionFiles ?? []) {
      if (state.loaded && isLegacyImport(file.path, file.content, state.loaded.rules)) {
        add(state, 'conflict', 'Keysmith rules already loaded through a legacy instruction file')
        tell($, state, 'Legacy Keysmith instructions loaded; additional mod injection paused. See docs/mods.md.')
      }
    }
    if (options.mode !== 'context' || !state.loaded || blocked(state)) return next(e)
    state.contextObserved = true
    return next({ ...e, blocks: contextOf(e.blocks, state.loaded.rules) })
  })

  if (options.mode === 'runtime') {
    on('prompt.compose', async ($, e, next) => {
      await ensureLoaded($, state, options)
      if (!state.loaded || blocked(state)) return next(e)
      state.composeObserved = true
      return { sections: sectionsOf(state.loaded.rules, state.loaded.append) }
    })
  }

  on('command.run', { command: 'keysmith-status' }, async $ => {
    await ensureLoaded($, state, options)
    let verification = 'not observed; delivery unverified'
    if (options.mode === 'runtime' && state.loaded && !blocked(state)) {
      try {
        const result = await $.prompt.compose()
        const expected = sectionsOf(state.loaded.rules, state.loaded.append)
        verification = result.sections.length === expected.length &&
          expected.every((item, i) => {
            const actual = result.sections[i]
            return actual?.id === item.id && actual.text === item.text && actual.scope === item.scope
          }) ? 'verified composition (probe; model delivery requires a new-session smoke test)'
          : 'not verified: another mod or managed policy changed/skipped Keysmith composition'
      } catch {
        verification = 'composition probe unavailable; delivery unverified'
      }
    } else if (options.mode === 'context' && state.contextObserved && !blocked(state)) {
      verification = 'context hook applied; final delivery requires a new-session smoke test'
    }
    if (blocked(state)) verification = 'paused: load error or legacy configuration conflict'
    return { text: [
      `mode: ${options.mode}`,
      `rules file: ${state.loaded?.rulesPath ?? (options.rulesFile || '(bundled rules; not loaded)')}`,
      `append file: ${state.loaded?.appendPath ?? '(not loaded)'}`,
      `agent: ${state.registeredAgent ? 'keysmith:keysmith registered' : options.registerAgent ? 'not registered' : 'disabled'}`,
      `compose hook observed: ${state.composeObserved}`,
      `context hook observed: ${state.contextObserved}`,
      `verification: ${verification}`,
      ...(state.error ? [`error: ${state.error}`] : []),
      ...state.findings.map(item => `${item.kind}: ${item.detail}`),
      'Migration: docs/mods.md. Restart after cleanup/configuration changes; do not combine legacy runtime flags and this mod.',
    ].join('\n') }
  })
}
