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
    add(state, 'conflict', 'settings.systemPrompt 与 Keysmith 规则一致')
  }
  const home = await $.env.get('CLAUDE_KEYSMITH_HOME') ||
    await $.env.get('HOME') || await $.env.get('USERPROFILE')
  const configDir = await $.env.get('CLAUDE_CONFIG_DIR') || (home ? `${home}/.claude` : undefined)
  if (configDir) {
    const oldSystem = await readExisting($, `${configDir}/keysmith/system-prompt.md`)
    const oldAppend = await $.fs.exists(`${configDir}/keysmith/append-prompt.md`)
    if (oldSystem !== undefined || oldAppend) add(state, 'residue', '发现旧 runtime 提示词文件')
    if (oldSystem?.trim() && typeof configuredPrompt === 'string' &&
        configuredPrompt.trim() === oldSystem.trim()) {
      add(state, 'conflict', 'settings.systemPrompt 与已部署的旧 runtime 文件一致')
    }
    const memory = await readExisting($, `${configDir}/CLAUDE.md`)
    if (memory?.includes('<!-- claude-keysmith:start name=')) {
      add(state, 'conflict', '用户 CLAUDE.md 中存在 Keysmith 管理的 import')
    }
    const agent = await readExisting($, `${configDir}/agents/keysmith.md`)
    if (agent?.includes('<!-- claude-keysmith:start name=keysmith-agent -->')) {
      add(state, 'residue', '发现旧用户级 Keysmith agent（独立 agent 类型）')
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
        add(state, 'residue', '发现旧项目级 Keysmith agent（独立 agent 类型）')
      }
    } else {
      // ancestors() strips comments. Read the memory file itself for ownership
      // markers, including imports whose deployed rules differ from these rules.
      if (file.parts.some(part => isLegacyImport(part.path, part.content, prompts.rules)) ||
          raw?.includes('<!-- claude-keysmith:start name=') ||
          file.content.includes('<!-- claude-keysmith:start name=')) {
        add(state, 'conflict', '项目指令文件中存在 Keysmith 管理的 import')
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
      add(state, 'conflict', '存在 Keysmith 管理的 shell wrapper；使用 mod 前请清理并卸载已加载的 function')
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
          throw new Error('自定义提示词路径与当前操作系统不匹配')
        }
      }
      const rules = await $.fs.read(rulesPath)
      const append = appendPath ? await $.fs.read(appendPath) : ''
      if (!systemBody(rules).trim()) throw new Error('规则正文为空')
      const prompts = { rules, append, rulesPath, appendPath }
      await inspectLegacy($, state, prompts)
      state.loaded = prompts
    } catch {
      state.error = '无法读取提示词文件或检查旧配置；未应用 Keysmith 注入'
    }
    if (state.error) tell($, state, state.error)
    for (const finding of state.findings) {
      tell($, state, `${finding.kind}: ${finding.detail}。参见 docs/mods.md 和 /keysmith-status。`)
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
      name: 'keysmith-status', description: '显示 Keysmith mod 来源、冲突及提示词验证状态',
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
        tell($, state, 'Keysmith agent 注册失败；/keysmith-status 会单独报告')
      }
    }
    return next(e)
  })

  on('prompt.context', async ($, e, next) => {
    await ensureLoaded($, state, options)
    for (const file of e.instructionFiles ?? []) {
      if (state.loaded && isLegacyImport(file.path, file.content, state.loaded.rules)) {
        add(state, 'conflict', 'Keysmith 规则已通过旧指令文件加载')
        tell($, state, '已加载旧 Keysmith 指令，暂停新增 mod 注入。参见 docs/mods.md。')
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
    let verification = '尚未观察到 hook 调用；模型接收情况未验证'
    if (options.mode === 'runtime' && state.loaded && !blocked(state)) {
      try {
        const result = await $.prompt.compose()
        const expected = sectionsOf(state.loaded.rules, state.loaded.append)
        verification = result.sections.length === expected.length &&
          expected.every((item, i) => {
            const actual = result.sections[i]
            return actual?.id === item.id && actual.text === item.text && actual.scope === item.scope
          }) ? '提示词组成已验证（探测结果；模型接收情况需在新会话实测）'
          : '未验证：其他 mod 或组织策略修改/跳过了 Keysmith 提示词组成'
      } catch {
        verification = '提示词组成探测不可用；模型接收情况未验证'
      }
    } else if (options.mode === 'context' && state.contextObserved && !blocked(state)) {
      verification = 'context hook 已应用；模型最终接收情况需在新会话实测'
    }
    if (blocked(state)) verification = '已暂停：读取错误或旧配置冲突'
    return { text: [
      `模式：${options.mode}`,
      `规则文件：${state.loaded?.rulesPath ?? (options.rulesFile || '（内置规则；未加载）')}`,
      `追加文件：${state.loaded?.appendPath ?? '（未加载）'}`,
      `agent：${state.registeredAgent ? 'keysmith:keysmith 已注册' : options.registerAgent ? '未注册' : '已禁用'}`,
      `已观察到 compose hook：${state.composeObserved}`,
      `已观察到 context hook：${state.contextObserved}`,
      `验证：${verification}`,
      ...(state.error ? [`错误：${state.error}`] : []),
      ...state.findings.map(item => `${item.kind}: ${item.detail}`),
      '迁移说明：docs/mods.md。清理或配置变更后请开新会话；不要将旧 runtime 参数与此 mod 叠加使用。',
    ].join('\n') }
  })
}
