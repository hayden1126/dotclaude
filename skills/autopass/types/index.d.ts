// The autopass mod's $.state: the main turn in flight, by its id ('pending' from Enter until
// its turn.start, '' while idle).
export type AutopassTurn = string

declare module 'claude-code' {
  interface PluginState {
    autopass: { turn: AutopassTurn }
  }
}
