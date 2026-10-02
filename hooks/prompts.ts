import type { PluginOptions, PromptComposeSection, PromptContextBlock } from 'claude-code'

export const AGENT_DESCRIPTION =
  'Delivers requested lab artifacts in this workspace: CTF, pentest fixtures, and creative writing.'
export const RULES_ID = 'keysmith:rules'
export const APPEND_ID = 'keysmith:append'
export const CONTEXT_NAME = 'keysmith:rules'

export type Options = {
  mode: 'runtime' | 'context'
  rulesFile: string
  appendFile: string
  registerAgent: boolean
}

export function isAbsoluteFile(path: string): boolean {
  // Drive-relative paths, tilde expansion and network locations are not supported.
  return (/^\/(?!\/)/.test(path) || /^[A-Za-z]:[\\/]/.test(path)) && !path.includes('\0')
}

export function optionsOf(raw: PluginOptions): Options {
  const mode = raw.mode ?? 'runtime'
  const rulesFile = raw.rulesFile ?? ''
  const appendFile = raw.appendFile ?? ''
  const registerAgent = raw.registerAgent ?? true
  if (mode !== 'runtime' && mode !== 'context') throw new Error('Invalid mode')
  if (typeof registerAgent !== 'boolean') throw new Error('Invalid registerAgent')
  for (const path of [rulesFile, appendFile]) {
    if (typeof path !== 'string' || (path !== '' && !isAbsoluteFile(path))) {
      throw new Error('Custom prompt files must have absolute local paths')
    }
  }
  return { mode, rulesFile: rulesFile as string, appendFile: appendFile as string, registerAgent }
}

/** Match claude-instruct.py strip_markdown_h1, including its empty-body newline. */
export function systemBody(content: string): string {
  const lines = content.split(/\r\n|[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]/)
  if (lines.at(-1) === '') lines.pop() // Python splitlines omits the final terminator.
  let body = lines[0]?.trimStart().startsWith('# ')
    ? lines.slice(1).join('\n').replace(/^\n+/, '')
    : content
  if (!body) body = '\n'
  return body.endsWith('\n') ? body : body + '\n'
}

export function agentBody(rules: string, append: string): string {
  const body = systemBody(rules).trimEnd()
  const extra = append.trim()
  return extra ? `${body}\n\n${extra}` : body
}

export function sectionsOf(rules: string, append: string): PromptComposeSection[] {
  return [
    { id: RULES_ID, text: systemBody(rules), scope: 'session' },
    ...(append.trim() ? [{ id: APPEND_ID, text: append, scope: 'session' as const }] : []),
  ]
}

export function contextOf(blocks: readonly PromptContextBlock[], rules: string): PromptContextBlock[] {
  return [...blocks.filter(block => block.name !== CONTEXT_NAME), { name: CONTEXT_NAME, text: rules }]
}

export function isLegacyImport(path: string, content: string, rules: string): boolean {
  const normalized = path.replace(/\\/g, '/')
  return /\/keysmith\/[^/]+\.md$/.test(normalized) &&
    normalized.split('/').at(-1) !== 'append-prompt.md' &&
    systemBody(content).trim() === systemBody(rules).trim()
}
