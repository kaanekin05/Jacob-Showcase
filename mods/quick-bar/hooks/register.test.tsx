import { expect, test } from 'claude-code/testing'

import { GROUPS, stepLabel } from './register'

test('a step label names the tool and its main argument', async () => {
  expect(stepLabel('Read', { file_path: 'Assets/Player.cs' })).toBe('Read: Assets/Player.cs')
  expect(stepLabel('Bash', { command: 'git status\n  --short', description: 'Show status' })).toBe('Bash: git status --short')
  expect(stepLabel('TodoWrite', { todos: [] })).toBe('TodoWrite')
  expect(stepLabel('Bash', { command: 'x'.repeat(200) })).toHaveLength(70)
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`a tool call shows in Steps while the turn runs (${surface})`, async ($, on) => {
    on('tool.call', async () => ({ result: 'ok' }) as never)
    await $.tool.call({ tool: 'Bash', command: 'ls -la' } as never)
    const ui = await $.ui.mount({
      plugin: 'quick-bar',
      surface,
      component: 'Pane',
      requestId: 'quick-bar',
      props: { bodyColumns: 30 } as never,
    })

    expect(await ui.find({ type: 'Text', text: /Bash: ls -la/ })).toBeDefined()
  })
}

const filled: string[] = []
const closed: string[] = []

for (const surface of ['terminal', 'desktop'] as const) {
  test(`a press fills the prompt box (${surface})`, async ($, on) => {
    on('prompt.fill', async (_$, e) => {
      filled.push(e.text)

      return { isFilled: true }
    })
    on('ui.close', async (_$, e) => {
      closed.push(e.id)

      return { value: undefined }
    })
    const ui = await $.ui.mount({
      plugin: 'quick-bar',
      surface,
      component: 'Pane',
      requestId: 'quick-bar',
      props: { bodyColumns: 30 } as never,
    })

    expect(await ui.findAll({ type: 'Button' })).toHaveLength(GROUPS.flatMap(g => g.items).length + 1)
    await ui.press({ key: 'triage-repo' })
    expect(filled.at(-1)).toBe('/triage-repo ')
    await ui.press({ key: 'continue' })
    expect(filled.at(-1)).toMatch(/^Continue where you left off\./)
    await ui.press({ key: 'close' })
    expect(closed.at(-1)).toBe('quick-bar')
  })
}
