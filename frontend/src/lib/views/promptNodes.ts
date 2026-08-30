// The prompt DISPOSITION vocabulary (#951/#1684) — which shelf a prompt belongs
// on, derived from its own `context_strategy.output`. The VALUES are computed
// backend-side (`prompts.py::_prompt_computed_metadata`, mirroring assistants'
// `listed`) and arrive on every summary in `computed_metadata`; the schema
// declares `disposition`/`runnable` as computed `select` fields on
// `prompt:base`, so `fieldValue` routes reads to `computed_metadata` and the
// view designer offers them like any other field. This module keeps only the
// label/key constants the frontend still names in code — the built-in view
// predicates and the chat lift — pinned to the backend strings by
// spec/prompt-disposition-labels.json (both test suites assert against it).

// The computed-field keys (the schema declares both on `prompt:base`).
export const DISPOSITION_FIELD = "disposition";
export const RUNNABLE_FIELD = "runnable";

// The `runnable` field's single truthy value ("" when not runnable): a prompt
// is runnable — launchable as a standalone chat (#1433) — iff its disposition
// is Chat AND it is anchored to no host type (`offer_on` empty).
export const RUNNABLE_LABEL = "runnable";

// The two dispositions a conversation seed can carry, exported so chatNodes'
// seed-disposition descriptor and the "Openable chats" predicate bind to the
// same label strings the backend stamps (a rename can't drift them).
export const CHAT_DISPOSITION_LABEL = "Chat";
export const REVISE_ENTITIES_DISPOSITION_LABEL = "Revise entities";
