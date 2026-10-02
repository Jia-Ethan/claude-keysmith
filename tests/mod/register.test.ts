import { describe, expect, test } from 'claude-code/testing'
import {
  AGENT_DESCRIPTION, CONTEXT_NAME, agentBody, contextOf, isAbsoluteFile,
  optionsOf, sectionsOf, systemBody,
} from '../../hooks/prompts'
import options from './fixtures/options'
import { APPEND, BASE, BLOCKS, COMPOSE, RULES, SESSION, world } from './fixtures/world'

describe('Keysmith native hooks', () => {
  test('replaces the system prompt only in runtime mode and preserves context', async ($, on) => {
    const fixture = world(on)
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(
      options.mode === 'runtime' ? sectionsOf(RULES, APPEND) : BASE,
    )
    const context = await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })
    expect(context.blocks).toEqual(options.mode === 'context' ? contextOf(BLOCKS, RULES) : BLOCKS)
    expect(fixture.agents).toEqual(options.registerAgent ? [{
      name: 'keysmith', description: AGENT_DESCRIPTION, prompt: agentBody(RULES, APPEND),
    }] : [])
    const appendReads = fixture.reads.filter(path =>
      (options.appendFile && path.replace(/\\/g, '/').endsWith(options.appendFile.replace(/\\/g, '/'))) ||
      path.replace(/\\/g, '/').endsWith('/claude-append-prompt.md'),
    )
    expect(appendReads.length).toBe(options.mode === 'runtime' || options.registerAgent ? 1 : 0)
  })

  test('repeated compositions, context reads and starts do not duplicate text', async ($, on) => {
    const fixture = world(on)
    await $.session.start(SESSION)
    const first = await $.prompt.compose(COMPOSE)
    expect(await $.prompt.compose(COMPOSE)).toEqual(first)
    const firstContext = await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })
    const secondContext = await $.prompt.context({ ...firstContext, instructionFiles: [] })
    expect(secondContext).toEqual(firstContext)
    await $.session.start(SESSION)
    expect(fixture.reads.length).toBe(options.mode === 'runtime' || options.registerAgent ? 2 : 1)
    expect(fixture.agents.length).toBe(options.registerAgent ? 2 : 0) // Same name replaces its definition.
  })

  test('empty custom append adds no blank system section or agent suffix', async ($, on) => {
    const fixture = world(on, { append: '' })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(
      options.mode === 'runtime' ? sectionsOf(RULES, '') : BASE,
    )
    if (options.registerAgent) expect(fixture.agents[0]?.prompt).toBe(systemBody(RULES).trimEnd())
  })

  for (const fail of ['rules', 'settings', 'ancestors'] as const) {
    test(`${fail} failure retains the original prompt, with no agent or secret in diagnostics`, async ($, on) => {
      const fixture = world(on, { fail })
      await $.session.start(SESSION)
      expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
      expect((await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })).blocks).toEqual(BLOCKS)
      expect(fixture.agents).toEqual([])
      const status = await $.command.run({ command: 'keysmith-status', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })
      expect(status.text).toContain('paused:')
      expect(status.text).not.toContain('SECRET_ERROR_SENTINEL')
      expect(fixture.logs.join('\n')).not.toContain('SECRET_ERROR_SENTINEL')
    })
  }

  test('append failure cannot partially replace the runtime prompt or register an agent', async ($, on) => {
    const fixture = world(on, { fail: 'append' })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
    expect(fixture.agents).toEqual([])
    const context = await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })
    expect(context.blocks).toEqual(options.mode === 'context' && !options.registerAgent ? contextOf(BLOCKS, RULES) : BLOCKS)
  })

  test('empty rules retain the original prompt', async ($, on) => {
    world(on, { rules: '# Empty\n' })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
  })

  for (const [title, files, settings] of [
    ['managed user import', { '/home/test/.claude/CLAUDE.md': '<!-- claude-keysmith:start name=custom -->\n@keysmith/custom.md\n<!-- claude-keysmith:end name=custom -->' }, {}],
    ['managed wrapper', { '/home/test/.zshrc': '# >>> claude-keysmith runtime >>>\nwrapper\n# <<< claude-keysmith runtime <<<' }, {}],
    ['matching settings prompt', {}, { systemPrompt: systemBody(RULES), env: { TOKEN: 'SECRET_TOKEN_SENTINEL' } }],
    ['older deployed settings prompt', { '/home/test/.claude/keysmith/system-prompt.md': 'OLDER_RULES' }, { systemPrompt: 'OLDER_RULES' }],
  ] as const) {
    test(`${title} pauses new injection without changing legacy files`, async ($, on) => {
      const fixture = world(on, { files, settings })
      await $.session.start(SESSION)
      expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
      expect((await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })).blocks).toEqual(BLOCKS)
      expect(fixture.agents).toEqual([])
      const status = await $.command.run({ command: 'keysmith-status', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })
      expect(status.text).toContain('conflict:')
      expect(status.text).not.toContain('SECRET_TOKEN_SENTINEL')
    })
  }

  test('project import ownership is detected before the first composition', async ($, on) => {
    world(on, { ancestors: [{
      dir: '/repo', name: 'CLAUDE.md', content: 'Project notes',
      parts: [{ path: '/repo/.claude/keysmith/custom.md', content: RULES }],
    }] })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
  })

  test('loaded legacy rule imports pause subsequent injection', async ($, on) => {
    world(on)
    await $.session.start(SESSION)
    const input = { blocks: BLOCKS, instructionFiles: [{
      path: '/repo/.claude/keysmith/custom.md', kind: 'project' as const, content: RULES,
    }] }
    expect((await $.prompt.context(input)).blocks).toEqual(BLOCKS)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
  })

  test('raw project ownership markers catch older or different imported rules', async ($, on) => {
    world(on, {
      files: { '/repo/CLAUDE.local.md': '<!-- claude-keysmith:start name=older-custom -->\n@.claude/keysmith/older-custom.md\n<!-- claude-keysmith:end name=older-custom -->' },
      ancestors: [{ dir: '/repo', name: 'CLAUDE.local.md', content: 'OLDER_RULES', parts: [
        { path: '/repo/.claude/keysmith/older-custom.md', content: 'OLDER_RULES' },
      ] }],
    })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
  })

  test('unreferenced runtime files and a separate owned agent are only residue', async ($, on) => {
    const fixture = world(on, { files: {
      '/home/test/.claude/keysmith/system-prompt.md': 'OLD',
      '/home/test/.claude/agents/keysmith.md': '<!-- claude-keysmith:start name=keysmith-agent -->',
    } })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(options.mode === 'runtime' ? sectionsOf(RULES, APPEND) : BASE)
    expect(fixture.logs.join('\n')).toContain('residue:')
    expect(fixture.logs.join('\n')).not.toContain('conflict:')
  })

  test('status distinguishes successful composition from a delivery claim', async ($, on) => {
    world(on)
    await $.session.start(SESSION)
    await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })
    const status = await $.command.run({ command: 'keysmith-status', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })
    expect(status.text).toContain(`mode: ${options.mode}`)
    expect(status.text).toContain(options.mode === 'runtime' ? 'verified composition (probe;' : 'context hook applied;')
    expect(status.text).toContain('smoke test')
  })

  test('agent registration failure leaves main prompt support available', async ($, on) => {
    world(on, { agentFails: true })
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(options.mode === 'runtime' ? sectionsOf(RULES, APPEND) : BASE)
    const status = await $.command.run({ command: 'keysmith-status', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })
    expect(status.text).toContain(options.registerAgent ? 'agent: not registered' : 'agent: disabled')
  })

  test('managed prompt hooks can skip user mods without a fallback injection', {
    plugins: [{
      name: 'managed-guard', tier: 'prepend',
      register(on) {
        // A test's argument-free probe has no live session facts. Answer that mock
        // directly; normal renders use the same tier skip as sec-default.
        on('prompt.compose', ($, e, next) => e.promptModel ? next.to(e, 'append') : {
          sections: [{ id: 'intro', text: 'DEFAULT_SYSTEM', scope: 'shared' }],
        })
        on('prompt.context', ($, e, next) => next.to(e, 'append'))
      },
    }],
  }, async ($, on) => {
    world(on)
    await $.session.start(SESSION)
    expect((await $.prompt.compose(COMPOSE)).sections).toEqual(BASE)
    expect((await $.prompt.context({ blocks: BLOCKS, instructionFiles: [] })).blocks).toEqual(BLOCKS)
    const status = await $.command.run({ command: 'keysmith-status', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } })
    expect(status.text).toContain(options.mode === 'runtime' ? 'not verified:' : 'not observed;')
  })

  test('refused plugin applies no effects before the host reports refusal', {
    plugins: [{
      name: 'admission-guard', tier: 'prepend',
      register(on) {
        on('plugin.register', { name: 'keysmith' }, () => ({ refuse: 'Disabled for this test' }))
      },
    }],
  }, async ($, on) => {
    const fixture = world(on)
    let refusal = ''
    try { await $.session.start(SESSION) } catch (error) { refusal = String(error) }
    expect(refusal).toContain('refused by admission-guard')
    expect(fixture.agents).toEqual([])
    expect(fixture.reads).toEqual([])
  })

  test('path and whitespace behavior matches the legacy carriers', () => {
    expect(systemBody('  # 标题\r\n\r\n正文\r\n')).toBe('正文\n')
    expect(systemBody('# Heading\nBody\n\n')).toBe('Body\n')
    expect(systemBody('# Heading\u2028Body')).toBe('Body\n')
    expect(systemBody('No heading')).toBe('No heading\n')
    expect(agentBody('# Rules\n\nBody  \n', '  Extra\n')).toBe('Body\n\nExtra')
    expect(isAbsoluteFile('/中文/space dir/rules.md')).toBe(true)
    expect(isAbsoluteFile('C:\\中文\\space dir\\rules.md')).toBe(true)
    for (const path of ['relative.md', '~/rules.md', 'C:relative.md', '\\\\server\\rules.md', '//server/rules.md']) {
      expect(() => optionsOf({ rulesFile: path })).toThrow('absolute local paths')
    }
    expect(contextOf([{ name: CONTEXT_NAME, text: 'old' }, ...BLOCKS], RULES)).toEqual(contextOf(BLOCKS, RULES))
  })
})
