export type RoleRow = { role: string; lines: string[] }
export type CommitRow = { sha: string; author: string; ago: string; subject: string }
export type Board = {
  updated: string
  fetchOk: boolean
  head: string
  contract: string
  roles: RoleRow[]
  commits: CommitRow[]
  brainDone: string[]
  brainMissing: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'team-board': { board: Board }
  }
}
