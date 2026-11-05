export type Meter = { percent: number | null; window: number }
export type Step = { id: string; label: string; isSubagent: boolean }
export type Steps = { count: number; rows: Step[] }

declare module 'claude-code' {
  interface PluginState {
    'quick-bar': { meter: Meter; steps: Steps }
  }
}
