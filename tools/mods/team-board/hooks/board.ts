import type { Board, CommitRow, RoleRow } from '../types'

export const ROLES = ['brain', 'ears', 'voice', 'spine', 'mobile'] as const
export const BRAIN_MODULES = [
  'chunker', 'speakable', 'prompt', 'llama_client', 'llama_server', 'stage',
  'router', 'mock_cli', 'sim', 'bakeoff', 'ablate',
] as const
export const SEP = '\u001f'

export const EMPTY: Board = {
  updated: '', fetchOk: false, head: '', contract: '',
  roles: [], commits: [], brainDone: [], brainMissing: [],
}

/** First `max` bullets under "## Status" of a handoff file. */
export function parseStatus(md: string, max = 3): string[] {
  const lines = md.split(/\r?\n/)
  const start = lines.findIndex(l => /^##\s+Status/i.test(l))
  if (start < 0) return []
  const out: string[] = []
  for (const line of lines.slice(start + 1)) {
    if (/^##\s/.test(line)) break
    const m = line.match(/^\s*[-*]\s+(.*)$/)
    if (m) out.push(m[1].replace(/\*\*/g, '').trim())
    if (out.length >= max) break
  }
  return out
}

/** `git log --format=%h<SEP>%an<SEP>%ar<SEP>%s` → rows. */
export function parseLog(stdout: string): CommitRow[] {
  return stdout.split(/\r?\n/).filter(Boolean).map(line => {
    const [sha = '', author = '', ago = '', subject = ''] = line.split(SEP)
    return { sha, author, ago, subject }
  })
}

/** `git ls-tree --name-only origin/main brain/` → which Brain modules exist. */
export function splitModules(lsTree: string): { done: string[]; missing: string[] } {
  const files = new Set(lsTree.split(/\r?\n/).map(f => f.replace(/^brain\//, '')))
  const done = BRAIN_MODULES.filter(m => files.has(`${m}.py`))
  return { done: [...done], missing: BRAIN_MODULES.filter(m => !files.has(`${m}.py`)) }
}

export function roleRow(role: string, md: string | null): RoleRow {
  if (md === null) return { role, lines: ['no handoff file yet'] }
  const lines = parseStatus(md)
  return { role, lines: lines.length ? lines : ['handoff has no "## Status" bullets'] }
}

export function statusLine(b: Board): string {
  const withHandoff = b.roles.filter(r => r.lines[0] !== 'no handoff file yet').length
  const latest = b.commits[0]
  return `board: brain ${b.brainDone.length}/${BRAIN_MODULES.length} · handoffs ${withHandoff}/${ROLES.length}` +
    (latest ? ` · main ${latest.ago}` : '') + (b.fetchOk ? '' : ' · offline')
}

export const CONTRACT_PATH = /(^|[\\/])docs[\\/]CONTRACT\.md$/
