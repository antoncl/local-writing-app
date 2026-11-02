<script lang="ts">
  // Settings → Proofreading: Harper's rules in its groups (ADR-0102 §4). Each
  // group is a disclosure, collapsed until the writer searches or filters; each
  // rule a plain row with a three-way choice (Inherit / On / Off) for one level.
  // Rules are not nodes, so these are not NodeRows.
  import type { RuleGroup } from "@/lib/proofread/findings";
  import { HARPER_DEFAULT, inheritedRule } from "@/lib/proofread/settingsView";
  import type { ProofreadingLayer, ProofreadingSetup } from "@/lib/types";

  let {
    groups,
    setup,
    layer,
    readonly = false,
    forceOpen = false,
    busy,
    onSet,
  }: {
    groups: RuleGroup[];
    setup: ProofreadingSetup;
    /** The level being edited. */
    layer: ProofreadingLayer;
    readonly?: boolean;
    /** A search or the changed filter is on: show every group that has matches. */
    forceOpen?: boolean;
    /** Names with a write in flight. */
    busy: Set<string>;
    onSet: (rule: string, enabled: boolean | null) => void;
  } = $props();

  let opened = $state(new Set<string>());

  function toggle(label: string): void {
    const next = new Set(opened);
    if (!next.delete(label)) next.add(label);
    opened = next;
  }

  const CHOICES: { label: string; value: boolean | null }[] = [
    { label: "Inherit", value: null },
    { label: "On", value: true },
    { label: "Off", value: false },
  ];

  function inheritedText(rule: string, harperDefault: boolean): string {
    const { value, from } = inheritedRule(setup, layer.id, rule, harperDefault);
    return `${value ? "On" : "Off"} — ${from === HARPER_DEFAULT ? HARPER_DEFAULT : `set by ${from}`}`;
  }
</script>

{#each groups as group (group.label)}
  {@const open = forceOpen || opened.has(group.label)}
  <div class="group">
    <button type="button" class="group-head" aria-expanded={open} disabled={forceOpen} onclick={() => toggle(group.label)}>
      <span class="caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <span class="group-label">{group.label}</span>
      <span class="count">{group.rules.length}</span>
    </button>
    {#if open}
      {#if group.description}<p class="group-note">{group.description}</p>{/if}
      <ul class="rules">
        {#each group.rules as rule (rule.name)}
          {@const own = layer.rules[rule.name] ?? null}
          <li class="rule">
            <div class="rule-text">
              <span class="rule-label">{rule.label}</span>
              {#if rule.description}<span class="rule-desc">{rule.description}</span>{/if}
              {#if own === null}<span class="rule-desc">{inheritedText(rule.name, rule.default)}</span>{/if}
            </div>
            <div class="choice" role="group" aria-label={`${rule.label} at ${layer.label}`}>
              {#each CHOICES as choice (choice.label)}
                <button
                  type="button"
                  class:active={own === choice.value}
                  aria-pressed={own === choice.value}
                  disabled={readonly || busy.has(rule.name)}
                  onclick={() => onSet(rule.name, choice.value)}
                >{choice.label}</button>
              {/each}
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/each}

<style>
  .group {
    border-bottom: 1px solid var(--divider);
  }

  .group-head {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    background: none;
    border: none;
    color: var(--text-1);
    text-align: left;
    padding: 6px 2px;
  }
  /* While filtering every group with matches is open: the head is a label. */
  .group-head:disabled {
    cursor: default;
    color: var(--text-1);
  }

  .group-label {
    flex: 1;
  }

  .count,
  .caret {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .group-note {
    margin: 0 0 4px 18px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .rules {
    list-style: none;
    margin: 0;
    padding: 0 0 6px 18px;
  }

  .rule {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 4px 0;
  }

  .rule-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .rule-label {
    color: var(--text-1);
  }

  .rule-desc {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .choice {
    display: flex;
    flex: none;
    background: var(--inset);
    border-radius: 6px;
  }

  .choice button {
    background: none;
    border: none;
    color: var(--text-2);
    font-size: var(--fs-sm);
    padding: 3px 8px;
  }

  .choice button.active {
    color: var(--accent);
    font-weight: 600;
  }
</style>
