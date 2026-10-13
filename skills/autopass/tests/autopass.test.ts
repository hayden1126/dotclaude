// The autopass mod under `claude plugin test`: the test's hooks stand for the engine beneath it,
// so `process.run` answers here as the toggle script would, and nothing runs on the host.
import { expect, test } from 'claude-code/testing'
import type { CommandSpec, On, ProcessRunResult, TurnCompleteInput } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const SID = 'sid-1'
const CWD = '/work'
const RUN = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 } } as const

type Answer = Partial<ProcessRunResult> | Error
type Engine$ = { argv: readonly string[]; timeoutMs?: number }

// Stands for the engine: the session, the command registry, the host and the transcript. Each
// `process.run` takes the next answer (the last one repeats) and is recorded.
function engine(on: On, answers: Answer[]) {
  const seen = { ran: [] as Engine$[], logged: [] as string[], registered: [] as CommandSpec[] }
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: CWD }))
  on('command.register', ($, e) => {
    seen.registered.push(e)
    return { value: { command: e.name } }
  })
  on('process.run', ($, e) => {
    seen.ran.push({ argv: e.argv, timeoutMs: e.init?.timeoutMs })
    const answer = answers[Math.min(seen.ran.length, answers.length) - 1]
    if (answer instanceof Error) return { deny: answer.message }  // the call rejects
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false,
      isStderrTruncated: false, ...answer } }
  })
  on('ui.log', ($, e) => {
    seen.logged.push(e.text)
    return { value: undefined }
  })
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  return seen
}

const start = ($: Engine) =>
  $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })

const autopass = ($: Engine, args: string) => $.command.run({ command: 'autopass', args, ...RUN })

const completed = (turnId: string, more: Partial<TurnCompleteInput> = {}) =>
  ({ answer: '', durationMs: 1, isAborted: false, turnId, reason: 'answer', ...more }) as TurnCompleteInput

const ON = 'on in this tab: it nudges a handoff at each context tier.'

test('registers /autopass as an immediate command', async ($, on) => {
  const seen = engine(on, [{}])
  await start($)
  expect(seen.registered).toEqual([{ name: 'autopass', argumentHint: 'on|off|status',
    immediate: true, description: 'Turn auto-pass on or off for this tmux tab, or show its status' }])
})

test('idle: the args reach the script unchanged and its reply is the output', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  await start($)
  for (const args of ['on', ' OFF ', '', 'status now']) {
    expect((await autopass($, args)).text).toBe(ON)
    expect(seen.ran.at(-1)?.argv.slice(3)).toEqual(['autopass', SID, CWD, args])
  }
  expect(seen.ran[0]?.argv.slice(0, 2)).toEqual(['bash', '-c'])
  expect(seen.ran[0]?.argv[2]).toBe('exec python3 -I "$HOME/.claude/hooks/autopass_toggle.py" "$@"')
  expect(seen.ran[0]?.timeoutMs).toBe(10_000)
  expect(seen.logged).toEqual([])
})

test('mid-turn: the reply is a notice at once and the command prints nothing', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  await start($)
  await $.turn.start({ text: 'work', turnId: 'main-1' })
  expect((await autopass($, 'on')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
})

test('a subagent completing leaves the main turn running', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  await start($)
  await $.turn.start({ text: 'work', turnId: 'main-1' })
  // Probed on 2.1.296 a subagent's run ends with its own id; one carrying the main id must not
  // clear it either.
  await $.turn.complete(completed('sub-9', { agentId: 'a-1' }))
  await $.turn.complete(completed('main-1', { agentId: 'a-2' }))
  expect((await autopass($, 'status')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
  await $.turn.complete(completed('main-1'))
  expect((await autopass($, 'status')).text).toBe(ON)
  expect(seen.logged).toEqual([ON])
})

test('an interrupted turn clears it too', async ($, on) => {
  engine(on, [{ stdout: ON + '\n' }])
  await start($)
  await $.turn.start({ text: 'work', turnId: 'main-2' })
  await $.turn.complete(completed('main-2', { isAborted: true, reason: 'aborted' }))
  expect((await autopass($, '')).text).toBe(ON)
})

test('between Enter and turn.start the reply is a notice', async ($, on) => {
  let release = () => {}
  const held = new Promise<void>(resolve => { release = resolve })
  const seen = engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', async ($, e) => {
    await held  // the UserPromptSubmit settings hooks, still running
    return { text: e.text, origin: e.origin }
  })
  await start($)
  const submitted = $.prompt.submit({ text: 'work', wait: false, origin: { kind: 'composer' } })
  expect((await autopass($, 'on')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
  release()
  await submitted
})

test('a prompt whose turn starts keeps that turn running after submit settles', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', async (_, e) => {
    await $.turn.start({ text: e.text, turnId: 't1' })  // as live: next(e) settles after it
    return { text: e.text, origin: e.origin }
  })
  await start($)
  await $.prompt.submit({ text: 'work', wait: false, origin: { kind: 'composer' } })
  expect((await autopass($, 'on')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
  await $.turn.complete(completed('t1'))
  expect((await autopass($, 'on')).text).toBe(ON)
})

test('a dropped prompt leaves the session idle', async ($, on) => {
  engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', () => ({ drop: 'blocked by a hook' }))
  await start($)
  await $.prompt.submit({ text: 'work', wait: false, origin: { kind: 'composer' } })
  expect((await autopass($, 'on')).text).toBe(ON)
})

test('a prompt typed into a running turn leaves its id alone', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', ($, e) => ({ text: e.text, origin: e.origin }))
  await start($)
  await $.turn.start({ text: 'work', turnId: 'main-1' })
  await $.prompt.submit({ text: 'more', wait: false, origin: { kind: 'composer' }, turnId: 'main-1' })
  expect((await autopass($, 'on')).text).toBeUndefined()  // still main-1's
  await $.turn.complete(completed('main-1'))
  expect((await autopass($, 'on')).text).toBe(ON)
  expect(seen.logged).toEqual([ON])
})

test('a prompt naming a turn that already ended is marked as its own', async ($, on) => {
  let release = () => {}
  const held = new Promise<void>(resolve => { release = resolve })
  const seen = engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', async ($, e) => {
    await held
    return { text: e.text, origin: e.origin }
  })
  await start($)
  const submitted = $.prompt.submit({ text: 'late', wait: false, origin: { kind: 'composer' },
    turnId: 'ended-1' })
  expect((await autopass($, 'on')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
  release()
  await submitted
})

test('a submission that starts no turn, or fails, leaves the session idle', async ($, on) => {
  let calls = 0
  engine(on, [{ stdout: ON + '\n' }])
  on('prompt.submit', ($, e) => {
    calls += 1
    if (calls === 2) throw new Error('interrupted')  // skipped; nothing beneath answers
    return { text: e.text, origin: e.origin }  // entered, but no turn.start follows
  })
  await start($)
  await $.prompt.submit({ text: '/model', wait: false, origin: { kind: 'composer' } })
  expect((await autopass($, 'on')).text).toBe(ON)
  await expect($.prompt.submit({ text: 'x', wait: false, origin: { kind: 'composer' } }))
    .rejects.toThrow()
  expect((await autopass($, 'on')).text).toBe(ON)
})

test('unreadable turn state counts as busy, so the reply still shows at once', async ($, on) => {
  const seen = engine(on, [{ stdout: ON + '\n' }])
  on('state.get', () => ({ deny: 'state unavailable' }))
  await start($)
  expect((await autopass($, 'on')).text).toBeUndefined()
  expect(seen.logged).toEqual([ON])
})

test('a failing script says so instead of going quiet', async ($, on) => {
  engine(on, [
    { exitCode: 2, stderr: 'Traceback\nModuleNotFoundError: autopass_state\n' },
    { exitCode: 0, stdout: '  \n' },
    new Error('spawn bash ENOENT'),
  ])
  await start($)
  expect((await autopass($, 'on')).text).toBe('the toggle failed (exit 2: ModuleNotFoundError: ' +
    'autopass_state); see /autopass status. Run ./setup.sh in dotclaude if it repeats.')
  expect((await autopass($, 'on')).text).toMatch(/^the toggle failed \(exit 0\); see \/autopass status/)
  expect((await autopass($, 'on')).text).toMatch(/^the toggle failed \(.*spawn bash ENOENT.*\)/)
})
