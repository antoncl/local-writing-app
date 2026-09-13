// The opener the implicit-context hover card follows a match with (#1923).
// App wires it at startup to the panes controller (`editorPanes.openLore`,
// failures to its error banner) the way it wires `editorPanes.setError`.
// editor-core cannot import that controller itself: the controller imports
// editor-core (autosave, the pane model), and the leaf widgets that host the
// highlight extension — a chat composer, a rail field, a wizard textarea —
// must not boot the whole pane graph on import. Unwired (in tests, or before
// App mounts) the card carries no link and the modifier click does nothing.
export const implicitContextOpener: { open: ((entryId: string) => void) | null } = { open: null };
