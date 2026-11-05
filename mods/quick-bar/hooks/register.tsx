import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Meter, Steps } from '../types'

const PANE = 'quick-bar'
const TITLE = 'Quick bar'
const meter = atom({ plugin: 'quick-bar', key: 'meter' } as const, {
  percent: null,
  window: 0,
} as Meter)

// The live step trail of the current prompt. textless hides the chat's own step rows while
// Claude works, so this is where a step can still be seen as it runs.
const steps = atom({ plugin: 'quick-bar', key: 'steps' } as const, { count: 0, rows: [] } as Steps)
// Rows kept on screen. Capped so the buttons below move at most this far.
const VISIBLE_STEPS = 12
const STEP_LABEL_CHARS = 70
// The argument that says most about a call, in order of preference.
const STEP_ARG_KEYS = ['command', 'file_path', 'pattern', 'url', 'query', 'description', 'skill', 'path', 'prompt']

export const stepLabel = (tool: string, input: Record<string, unknown>): string => {
  const arg = STEP_ARG_KEYS.map(key => input[key]).find(value => typeof value === 'string' && value.trim() !== '')
  const label = typeof arg === 'string' ? `${tool}: ${arg.replace(/\s+/g, ' ').trim()}` : tool

  return label.length > STEP_LABEL_CHARS ? `${label.slice(0, STEP_LABEL_CHARS - 1)}…` : label
}

// A trailing space marks a command that takes an argument: the press leaves
// the cursor ready for it. Every press only fills the prompt box; Enter runs it.
export const GROUPS: { title: string; items: { label: string; text: string }[] }[] = [
  {
    title: 'Jacob',
    items: [
      { label: 'check-updates', text: '/check-updates' },
      { label: 'commit-slices', text: '/commit-slices' },
      { label: 'deep-research', text: '/anthropic-skills:deep-research ' },
      { label: 'find-skills', text: '/find-skills ' },
      { label: 'handoff-brief', text: '/handoff-brief' },
      { label: 'karpathy-guidelines', text: '/karpathy-guidelines' },
      { label: 'no-ai-slop', text: '/no-ai-slop ' },
      { label: 'pm-check', text: '/pm-check ' },
      { label: 'session-finalizer', text: '/session-finalizer' },
      { label: 'skill-creator', text: '/anthropic-skills:skill-creator ' },
      { label: 'skill-doctor', text: '/skill-doctor' },
      { label: 'triage-repo', text: '/triage-repo ' },
      { label: 'unity-build', text: '/unity-build ' },
    ],
  },
  {
    title: 'Session',
    items: [
      { label: 'agents', text: '/agents' },
      { label: 'clear', text: '/clear' },
      { label: 'compact', text: '/compact' },
      { label: 'context', text: '/context' },
      { label: 'doctor', text: '/doctor' },
      { label: 'goal', text: '/goal ' },
      { label: 'login', text: '/login' },
      { label: 'model', text: '/model' },
      { label: 'plugin', text: '/plugin' },
      { label: 'resume', text: '/resume' },
    ],
  },
  {
    title: 'Prompts',
    items: [
      {
        label: 'continue',
        text: "Continue where you left off. The previous attempt was rate limited. Don't stop unless you encounter a problem or a question that I should be answering.",
      },
    ],
  },
]

const refreshMeter = async ($: EngineInterface) => {
  const { context } = await $.session.usage()
  await update($, meter, () => ({
    percent: context.percent ?? null,
    window: context.window,
  }))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'quick-bar',
      description: 'Open the quick bar: context meter and skill buttons',
    })
    void $.ui.open({ id: PANE, title: TITLE })
    void refreshMeter($)

    return next(e)
  })

  on('command.run', { command: 'quick-bar' }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: 'Quick bar opened.' }
  })

  on('prompt.submit', async ($, e, next) => {
    await update($, steps, () => ({ count: 0, rows: [] }))

    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const step = {
      id: String(e.tool_use_id ?? ''),
      label: stepLabel(String(e.tool), e as unknown as Record<string, unknown>),
      isSubagent: e.agentId !== undefined,
    }
    await update($, steps, s => ({ count: s.count + 1, rows: [...s.rows, step].slice(-VISIBLE_STEPS) }))

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    void refreshMeter($)

    return done
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const { percent, window } = await read($, meter)
    const { count, rows } = await read($, steps)
    const color = percent === null ? undefined : percent >= 80 ? 'red' : percent >= 60 ? 'yellow' : 'green'

    return (
      <Box flexDirection="column">
        <Text color={color}>
          {percent === null ? 'ctx --' : `ctx ${percent}% of ${Math.round(window / 1000)}k`}
        </Text>
        <Box flexDirection="column" marginTop={1}>
          <Text bold>{count > rows.length ? `Steps (last ${rows.length} of ${count})` : `Steps (${count})`}</Text>
          {rows.length === 0 ? (
            <Text dimColor>none yet</Text>
          ) : (
            rows.map((step, i) => (
              <Text key={`step-${i}-${step.id}`} dimColor={step.isSubagent} wrap="truncate-end">
                {step.isSubagent ? `↳ ${step.label}` : step.label}
              </Text>
            ))
          )}
        </Box>
        {GROUPS.map(group => (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>{group.title}</Text>
            {group.items.map(item => (
              <Button
                key={item.label}
                label={item.label}
                plain
                onPress={() => void $.prompt.fill({ text: item.text })}
              />
            ))}
          </Box>
        ))}
        <Box marginTop={1}>
          <Button key="close" label="close" role="dismiss" plain onPress={() => void $.ui.close({ id: PANE })} />
        </Box>
      </Box>
    )
  })
}
