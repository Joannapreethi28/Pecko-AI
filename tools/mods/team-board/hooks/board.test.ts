import { expect, test } from 'claude-code/testing'

import { parseLog, parseStatus, roleRow, splitModules, statusLine, CONTRACT_PATH, EMPTY, SEP } from './board'

test('parseStatus takes the first bullets under ## Status only', () => {
  const md = '# Brain\n## Status\n- ✅ **Plan** pushed\n- ⏳ Next: Task 1\n- three\n- four\n## Other\n- no'
  expect(parseStatus(md)).toEqual(['✅ Plan pushed', '⏳ Next: Task 1', 'three'])
  expect(parseStatus('# no status here')).toEqual([])
})

test('parseLog splits git log rows', () => {
  const out = `abc123${SEP}jabssyyy${SEP}2 minutes ago${SEP}brain: stage\n`
  expect(parseLog(out)).toEqual([{ sha: 'abc123', author: 'jabssyyy', ago: '2 minutes ago', subject: 'brain: stage' }])
})

test('splitModules marks Brain modules present on main', () => {
  const { done, missing } = splitModules('brain/stage.py\nbrain/prompt.py\nbrain/CLAUDE.md\n')
  expect(done).toEqual(['prompt', 'stage'])
  expect(missing.includes('router')).toBe(true)
})

test('roles without a handoff are flagged, status line counts them', () => {
  const roles = [roleRow('brain', '## Status\n- ok'), roleRow('ears', null)]
  expect(roles[1].lines).toEqual(['no handoff file yet'])
  const line = statusLine({ ...EMPTY, roles, fetchOk: false, brainDone: ['stage'] })
  expect(line).toBe('board: brain 1/11 · handoffs 1/5 · offline')
})

test('contract guard matches both path styles', () => {
  expect(CONTRACT_PATH.test(String.raw`C:\x\pecko\docs\CONTRACT.md`)).toBe(true)
  expect(CONTRACT_PATH.test('/home/u/pecko/docs/CONTRACT.md')).toBe(true)
  expect(CONTRACT_PATH.test('/home/u/pecko/docs/solution.md')).toBe(false)
})
