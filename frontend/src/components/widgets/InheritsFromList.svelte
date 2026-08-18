<script lang="ts">
  import type { DeclarationRow } from "@/lib/utils/projectChain";

  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";

  let {
    // The enumerated ancestor rows to offer (from `declarationRows`), outermost
    // first. `checked`/`toggleable` come from the model, never the DOM.
    rows,
    // A save is in flight — lock the boxes. Each request is derived from the
    // ancestors currently on screen, so a second click during the round trip
    // would compute from the stale enumeration and silently undo the first tick.
    // The create-time wizard has no round trip and leaves this false.
    busy = false,
    // The host owns the mutation. This list never trusts the browser's own toggle:
    // `onchange` puts the box straight back to the model value and lets the host
    // move it, because a save can fail (a 422, a vanished folder) and a ticked box
    // over an unchanged manifest is the one state this editor must never show. On
    // success the rows come back changed and Svelte flips the box. The wizard has
    // no round trip, so its rows re-derive synchronously to the same effect.
    onToggle = () => {},
  }: {
    rows: DeclarationRow[];
    busy?: boolean;
    onToggle?: (path: string) => void;
  } = $props();
</script>

<!--
  The shared declaration editor (#643 / ADR-0047 slice 4). One list, mounted by
  the post-hoc editor (Project pane) and the create-time wizard; the surrounding
  label, heading, and loading/empty chrome differ per host and stay there.

  `clickable={false}`: the checkbox IS the gesture, so the title must not also be
  a button competing for the same click. A disabled row is still shown — it is
  the organisational folder the walk crossed, and hiding it would leave a gap
  that reads as a defect. No `active`: that state means "open in a pane", and the
  checkbox is already the canonical indicator of what is declared.
-->
<NodeList isEmpty={false}>
  {#each rows as row (row.path)}
    <NodeRow title={row.label} detail={row.detail} clickable={false}>
      {#snippet leading()}
        <input
          type="checkbox"
          class="inherit-check"
          checked={row.checked}
          disabled={!row.toggleable || busy}
          aria-label={`Inherit from ${row.label}`}
          onchange={(event) => {
            event.currentTarget.checked = row.checked;
            onToggle(row.path);
          }}
        />
      {/snippet}
    </NodeRow>
  {/each}
</NodeList>

<style>
  /* `width: auto` is load-bearing, not tidying: styles.css sets
     `input, select { width: 100% }` for the app's form fields, and a checkbox in
     a flex row inherits it as its flex basis — the box ate the whole row and
     pushed the title off the right edge with zero width. `flex: none` alone does
     NOT fix it (basis `auto` reads the width property back); the width has to be
     overridden. Measured in the browser, not reasoned (the #426/#311 trap). */
  .inherit-check {
    flex: none;
    width: auto;
    margin: 0;
  }
  .inherit-check:disabled {
    opacity: 0.45;
  }
</style>
