# Application-global AI policy (#746)

## 1. Intent

Give the app a real, editable **default AI access policy** — the value every
project's `inherit` resolves to when nothing above it states one. Today that
value is a hardcoded `"off"` seed inside `_AIPolicyResolver`
(`lifecycle.py:89`): invisible, unchangeable, and standing in for the outermost
fallback the resolver walk never actually had.

This slice makes that fallback a real setting and gives it a control.

## 2. Why this is neither a project nor a per-folder file

The chain walk stops at the machine **root folder** (`default_projects_folder`,
#429). That folder is a *container*, not a project node — it has no
`project.md`, so there is no "root project" whose per-project policy could serve
as the default, and dropping a settings file *into* the root folder to fake one
would contaminate the user's own folder with app state. The app deliberately
keeps its config **out** of the projects: `config.yaml` lives in the per-user
config dir (`%APPDATA%/local-writing-app/`, `machine_settings.py:117-132`),
outside any project.

So the default policy is an **application-global** value — the outermost
fallback of the inheritance chain (`create-project-wizard.md` §2:
*"conceptually just the layer above the universe. When a project defers a field
all the way out, it lands here."*) — and its home is the machine config dir,
where the app already keeps this class of setting.

## 3. Storage — a field on `MachineSettings`, beside `display`

`MachineSettings` (`machine_settings.py:106-114`) already holds the other
application-global preferences the ADR names — `display` (theme / currency) and
`palette`. The default policy joins them:

```
MachineSettings:
  ...
  ai_policy: AIPolicy = "off"     # off | local-only | cloud-allowed
```

No new file, no new endpoint. Read/write ride the existing
`GET/PUT /api/settings/machine` path (`MachineSettingsUpdate` /
`MachineSettingsView` / `merge_update`), exactly as `display` does.

On the ADR's "application settings should travel, machine settings must not"
(§2): that is a **portability** distinction, not a file-layout one. `config.yaml`
today already mixes machine substrate (root folder, API keys) with app-global
prefs (`display`, `palette`); classifying keys into travel / no-travel is a
concern for a future settings-export feature, handled per-key within the one
file — not a reason to fork a second config file now for a single value.

## 4. Anti-goals

- **Not** an `"inherit"` option on the default. A floor cannot inherit from
  anything; it *is* the floor. Three concrete stops only: `off` / `local-only`
  / `cloud-allowed`.
- **Not** a change to `AIPolicy` or to per-project resolution semantics. The
  nearest-explicit-wins walk is untouched; only its *seed* changes.
- **Not** a migration of `display` / `palette` / currency into a new tier. This
  slice adds one field to where that class of setting already lives; the
  travel/no-travel split is deferred to whenever export exists.

## 5. Resolution — seed the walk instead of hardcoding

`_resolved_ai_policy` constructs `_AIPolicyResolver(self._stated_ai_policy)`
(`lifecycle.py:664`), which starts `self.policy = "off"`. Instead, seed it with
the app-global default, read **once per resolve** (one traversal, not per-layer
— [[feedback_one_traversal_not_six]]):

```
resolver = _AIPolicyResolver(self._stated_ai_policy, default=machine_settings.load_settings().ai_policy)
```

A project set to `inherit`, with nothing stated up its whole chain, now resolves
to the app default rather than a constant. Every other guarantee holds: a nearer
layer still overrides, and an unreadable manifest still falls closed to `off`
(`_stated_ai_policy`). The `AIPolicy` Literal type already bounds the machine
field, so a hand-edited garbage value is a Pydantic error on load, not a silent
mis-seed.

> **Cost note.** `_resolved_ai_policy` already carries a per-call manifest-read
> cost the code flags for the #466 memo. This adds one `load_settings()` read on
> the same path. It joins that same memo rather than growing a bespoke cache
> here.

## 6. The control — Settings → AI, explicit apply

The affordance lands in the **AI tab of the Settings dialog**
(`MachineSettingsDialog.svelte`) — already the single home for app-global
preferences (`display` lives there too), so no tier boundary leaks into the UI.

The control honors [[decisions_ai_permission_fails_closed]]: an **explicit
Apply**, never save-on-change — the same rule the per-project `AIPolicyModal`
follows. It reuses the three-stop presentation the policy already has, minus the
`inherit` stop (§4).

## 7. Wizard interaction (first run)

On **first run**, the AI step already establishes app substrate — provider
credentials and hired assistants are written to the shared layer, and the policy
slider **gates** them: pick `off` and no provider/assistant is created at all
(`showProviderSurface`, `createWizard.svelte.ts:166`; ADR §5). That gate is
correct and stays.

What changes: on first run the AI-step policy **writes the app-global default**
(there is no root project to hold it — §2), and the first project states
nothing, inheriting down to that default. This is what makes "the wizard sets
the global policy at startup" *true* rather than an illusion of the first
project sitting at the chain top. On **subsequent** project creation the AI-step
policy stays **per-project**, unchanged — the app default already exists and is
edited in Settings.

*Slice note:* §3, §5, §6 (field + resolver seed + Settings control) is the MVP
and closes #746's stated "done." §7's first-run write is the natural companion;
it is separable and can be a fast follow if this slice runs long.

## 8. User journey

1. **Fresh install, first project.** The wizard's AI step asks the policy once.
   Pick `cloud-allowed` → it becomes the app default; the new book inherits it.
   Pick `off` → app default is `off`, and no providers/assistants are set up.
2. **Later, change of mind.** Settings → AI shows the current app-wide default;
   change it and Apply. Every project on `inherit` with nothing stated above it
   now resolves to the new value — the knob that never existed before.
3. **A standalone project outside the chain.** Created `inherit`, it resolves to
   the app default instead of a silent hardcoded `off`.

## 9. Tests

- **Backend:** the machine `ai_policy` round-trips over `PUT /api/settings/machine`;
  an unset field defaults to `off`; a top-of-chain `inherit` resolves to the app
  default; a nearer layer still overrides it; a project's own explicit policy is
  unaffected.
- **Frontend:** the Settings → AI control renders the current default and Applies
  via `PUT /api/settings/machine` (explicit gesture, no save-on-change) — a mount
  test per [[reference_component_test_harness]].
- **Wizard (if §7 folded in):** first-run submit writes the app default and
  leaves the first project's policy unstated; subsequent creation writes
  per-project.
