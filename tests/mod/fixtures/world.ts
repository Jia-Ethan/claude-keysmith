import type { FsAncestor, On } from 'claude-code'
import { mock } from 'claude-code/testing'
import options from './options'

export const RULES = '# Project rules\n\n规则标记 RULE_SENTINEL\n'
export const APPEND = 'APPEND_SENTINEL\n'
export const BASE = [{ id: 'intro', text: 'DEFAULT_SYSTEM', scope: 'shared' as const }]
export const BLOCKS = [{ name: 'currentDate', text: 'today' }]
export const SESSION = { cwd: '/repo', surface: null, isInteractive: false } as const
export const COMPOSE = {
  model: 'test-model', promptModel: 'test-model', surfaces: [], tools: [], outputStyle: null, traits: [],
} as const

type WorldOptions = {
  rules?: string
  append?: string
  files?: Record<string, string>
  ancestors?: FsAncestor[]
  settings?: Record<string, unknown>
  fail?: 'rules' | 'append' | 'settings' | 'ancestors'
  agentFails?: boolean
}

export function world(on: On, config: WorldOptions = {}) {
  const rules = config.rules ?? RULES
  const append = config.append ?? APPEND
  const files = config.files ?? {}
  const reads: string[] = []
  const logs: string[] = []
  const agents: { name: string; prompt: string; description: string }[] = []
  mock.env(on, { HOME: '/home/test' })
  on('fs.read', ($, e) => {
    reads.push(e.path)
    const path = e.path.replace(/\\/g, '/')
    const existing = Object.keys(files).find(key => path.endsWith(key.replace(/\\/g, '/')))
    if (existing) return { value: files[existing] }
    if ((options.rulesFile && path.endsWith(options.rulesFile.replace(/\\/g, '/'))) || path.endsWith('/examples/claude-project-rules.md')) {
      if (config.fail === 'rules') throw new Error('SECRET_ERROR_SENTINEL')
      return { value: rules }
    }
    if ((options.appendFile && path.endsWith(options.appendFile.replace(/\\/g, '/'))) || path.endsWith('/examples/claude-append-prompt.md')) {
      if (config.fail === 'append') throw new Error('SECRET_ERROR_SENTINEL')
      return { value: append }
    }
    throw new Error('Unexpected file read')
  })
  on('fs.exists', ($, e) => ({ value: Object.keys(files).some(key =>
    e.path.replace(/\\/g, '/').endsWith(key.replace(/\\/g, '/')),
  ) }))
  on('fs.ancestors', () => {
    if (config.fail === 'ancestors') throw new Error('SECRET_ERROR_SENTINEL')
    return { value: config.ancestors ?? [] }
  })
  on('settings.read', () => {
    if (config.fail === 'settings') throw new Error('SECRET_ERROR_SENTINEL')
    return { value: config.settings ?? {} }
  })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('agent.register', ($, e) => {
    if (config.agentFails) throw new Error('SECRET_ERROR_SENTINEL')
    agents.push({ name: e.name, prompt: e.prompt, description: e.description })
    return { value: { agent: `keysmith:${e.name}` } }
  })
  on('ui.log', ($, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('prompt.compose', () => ({ sections: BASE }))
  on('prompt.context', ($, e) => ({ blocks: e.blocks, instructionFiles: e.instructionFiles }))
  return { reads, logs, agents, rules, append }
}
