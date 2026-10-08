import { atom, read, update } from 'claude-code'
import type { Hook, Register } from 'claude-code'

import type { Board } from '../types'
import { CONTRACT_PATH, EMPTY, ROLES, SEP, parseLog, roleRow, splitModules, statusLine } from './board'

type Dollar = Parameters<Hook<'session.start'>>[0]

const PANE = 'team-board'
const board = atom({ plugin: 'team-board', key: 'board' } as const, EMPTY)

async function git($: Dollar, args: string[], timeoutMs = 20000): Promise<string | null> {
  const r = await $.process.run(['git', ...args], { timeoutMs })
  return r.exitCode === 0 ? r.stdout : null
}

async function refresh($: Dollar): Promise<void> {
  const fetchOk = (await git($, ['fetch', '-q', 'origin', 'main'])) !== null
  const head = ((await git($, ['rev-parse', 'origin/main'])) ?? '').trim()
  if (!head) {
    $.ui.status('board: not a git repo with origin/main')
    return
  }
  const contract = ((await git($, ['rev-parse', 'origin/main:docs/CONTRACT.md'])) ?? '').trim()
  const commits = parseLog((await git($, ['log', 'origin/main', '-n', '8', `--format=%h${SEP}%an${SEP}%ar${SEP}%s`])) ?? '')
  const mods = splitModules((await git($, ['ls-tree', '--name-only', 'origin/main', 'brain/'])) ?? '')
  const roles = []
  for (const role of ROLES) roles.push(roleRow(role, await git($, ['show', `origin/main:${role}/handoff_${role}.md`])))

  const prev = await read($, board)
  if (prev.head && prev.head !== head) {
    const n = ((await git($, ['rev-list', '--count', `${prev.head}..${head}`])) ?? '?').trim()
    $.ui.toast(`main: ${n} new commit(s), latest "${commits[0]?.subject ?? ''}"`)
  }
  if (prev.contract && contract && prev.contract !== contract) {
    $.ui.toast('docs/CONTRACT.md changed on main: every role should re-read it', { timeoutMs: 10000 })
  }
  const next: Board = {
    updated: new Date().toLocaleTimeString(), fetchOk, head, contract,
    roles, commits, brainDone: mods.done, brainMissing: mods.missing,
  }
  await update($, board, () => next)
  $.ui.status(statusLine(next))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'team-board', description: 'Show the Pecko team board (refreshes from git every 60 s)' })
    $.clock.every(60000, () => void refresh($))
    void refresh($)
    void $.ui.open({ id: PANE, title: 'Team board' })
    return next(e)
  })

  on('command.run', { command: 'team-board' }, async $ => {
    await refresh($)
    await $.ui.open({ id: PANE, title: 'Team board' })
    return { text: 'Team board refreshed and opened.' }
  })

  // The contract is frozen: it changes only when all four roles agree (CLAUDE.md).
  const guard = (path: string) => CONTRACT_PATH.test(path)
    ? { deny: 'team-board: docs/CONTRACT.md is frozen. Agree the change with all four roles, then edit it by hand.' }
    : undefined
  on('tool.call', { tool: 'Edit' }, ($, e, next) => guard(e.file_path) ?? next(e))
  on('tool.call', { tool: 'Write' }, ($, e, next) => guard(e.file_path) ?? next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const b = await read($, board)
    const width = Math.max(30, (e.viewport?.columns ?? 60) - 2)
    const cut = (s: string) => (s.length > width ? `${s.slice(0, width - 1)}…` : s)
    if (!b.head) return <Text dimColor>Loading from git…</Text>
    return (
      <Box flexDirection="column">
        <Text dimColor>{cut(`updated ${b.updated}${b.fetchOk ? '' : ' (offline: last fetch)'}`)}</Text>
        <Text bold>Roles</Text>
        {b.roles.map(r => (
          <Box flexDirection="column">
            <Text>{cut(`${r.role.padEnd(6)} ${r.lines[0]}`)}</Text>
            {r.lines.slice(1).map(l => <Text dimColor>{cut(`       ${l}`)}</Text>)}
          </Box>
        ))}
        <Text bold>{`Brain modules ${b.brainDone.length}/${b.brainDone.length + b.brainMissing.length}`}</Text>
        <Text>{cut(b.brainDone.map(m => `✓${m}`).join(' '))}</Text>
        {b.brainMissing.length > 0 && <Text dimColor>{cut(b.brainMissing.map(m => `·${m}`).join(' '))}</Text>}
        <Text bold>Latest on main</Text>
        {b.commits.map(c => <Text>{cut(`${c.sha} ${c.ago.padEnd(14)} ${c.subject}`)}</Text>)}
      </Box>
    )
  })
}
