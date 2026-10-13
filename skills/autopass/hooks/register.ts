// /autopass on|off|status, served as an immediate slash command: typed mid-turn it runs at once
// instead of waiting for the turn to end. hooks/autopass_toggle.py (linked into ~/.claude/hooks
// by setup.sh) holds the rules and writes the tab flag; this module only runs it and shows its
// reply. The engine draws a command's `{ text }` only once the turn ends, so while a turn runs
// the reply goes out as a transcript notice instead (Hayden's pick, 2026-10-12). The child
// inherits the session's environment, so TMUX_PANE names the tab. Built on the 2.1.296 mod API.
import type { EngineInterface, Register } from 'claude-code'

// The main turn in flight, by id: PENDING from Enter until its turn.start, '' while idle. In
// $.state so a hot reload keeps it.
const TURN = { plugin: 'autopass', key: 'turn' } as const
const PENDING = 'pending'
// No plugin-root API exists, so the script is found where settings.json's hooks find theirs.
const TOGGLE = 'exec python3 -I "$HOME/.claude/hooks/autopass_toggle.py" "$@"'

// The flag may already be written when a later step fails, so this never says what changed.
const failed = (why: string) =>
  `the toggle failed (${why}); see /autopass status. Run ./setup.sh in dotclaude if it repeats.`

async function reply($: EngineInterface, args: string): Promise<string> {
  try {
    const [sid, cwd] = await Promise.all([$.session.id(), $.session.cwd()])
    const run = await $.process.run(['bash', '-c', TOGGLE, 'autopass', sid, cwd, args],
      { timeoutMs: 10_000 })
    const out = run.stdout.trim()
    if (run.exitCode === 0 && out) return out
    const err = run.stderr.trim().split('\n').at(-1)
    return failed(`exit ${run.exitCode}${err ? `: ${err}` : ''}`)
  } catch (err) {
    return failed(err instanceof Error ? err.message : String(err))
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'autopass',
      description: 'Turn auto-pass on or off for this tmux tab, or show its status',
      argumentHint: 'on|off|status',
      immediate: true,
    })
    return next(e)
  })

  // The UserPromptSubmit settings hooks run between Enter and turn.start, so a turn counts
  // from Enter: a prompt submitted while nothing runs marks it (a mod command raises no
  // prompt.submit). next(e) resolves only once the turn has started (probed on 2.1.296), and
  // turn.start's write moves the version on, so the clear in `finally` lands only on this
  // hook's own untouched mark: a drop, an error or a submission that started no turn. It uses
  // the version from that write, not a fresh get, since every get in one dispatch reads the
  // same moment. No .catch on purpose: a failing hook is skipped and the prompt goes through,
  // so this mod never stands between Hayden and a prompt.
  on('prompt.submit', async ($, e, next) => {
    const before = await $.state.get(TURN)
    if (before.value) return next(e)
    const mark = await $.state.set(TURN, PENDING, { ifVersion: before.version })
    try {
      return await next(e)
    } finally {
      if (mark.isSet) await $.state.set(TURN, '', { ifVersion: mark.version })
    }
  })

  on('turn.start', async ($, e, next) => {
    await $.state.set(TURN, e.turnId)
    return next(e)
  })

  // Only the main turn's own end clears it: a subagent's run completes too, with an agentId
  // (and, probed on 2.1.296, its own id). A Stop hook's block continues the same turn, and its
  // turn.complete comes once the continuation ends.
  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      const { value, version } = await $.state.get(TURN)
      if (value === e.turnId) await $.state.set(TURN, '', { ifVersion: version })
    }
    return next(e)
  })

  on('command.run', { command: 'autopass' }, async ($, e) => {
    const text = await reply($, e.args)
    // Unreadable state counts as a turn running: the notice shows at once either way.
    const turn = await $.state.get(TURN).then(read => read.value ?? '', () => 'unknown')
    if (!turn) return { text }
    $.ui.log(text)
    return {}
  }).catch(() => ({ text: failed('the autopass mod hook failed') }))
}
