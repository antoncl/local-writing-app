<script lang="ts">
  // What has changed underneath this snapshot since it was taken (ADR-0043,
  // #439 slice 3). Renders below the compare actions while parked.
  //
  // **The report IS the feature.** ADR-0043: if drift reporting is the only
  // protection an author gets, then a report that cannot name what actually
  // changed has not implemented the design, however correct the storage is. So
  // every row names the entity, and where the backend could tell, the field and
  // both values. The phrase "context has changed" appears nowhere, by design.
  //
  // **Advisory, always.** No gate, no acknowledgement, nothing to dismiss, and
  // Restore sits right beside it unaffected. The one thing this must not become
  // is a wall the author learns to walk through.
  //
  // Colour follows the compare view's one rule: cool = the snapshot's side,
  // warm = the scene as it is (§H). Nothing here draws a glyph — a snapshot
  // difference exists only while parked, and a glyph puts a permanent-looking
  // mark on a temporary condition (§J).
  import type { EntityDrift, SnapshotDrift, WitnessFieldDrift } from "@/lib/types";

  let { drift }: { drift: SnapshotDrift } = $props();

  /** A value as the author reads it. An absence renders as the same "(none)"
   *  the metadata rail uses — two spellings of nothing must not look like a
   *  change, which is what `same_rendered_value` already enforces on the wire. */
  function shown(value: unknown): string {
    if (value === null || value === undefined || value === "") return "(none)";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "(none)";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  /** The headline for one entity, in the author's vocabulary.
   *
   *  Membership is a claim about the *set* and needs its own wording, kept
   *  distinct from field drift: "this scene no longer references Chicago" is a
   *  different thing from "Chicago changed", and collapsing them would leave
   *  the author unable to tell which. */
  function headline(entity: EntityDrift): string {
    if (entity.membership === "removed") return "no longer part of this scene";
    if (entity.membership === "added") return "now part of this scene";
    if (entity.layer_now) return `now comes from ${entity.layer_now} (was ${entity.layer_was})`;
    // The floor (design doc §6): naming the entity is already a specific claim.
    // Reached when the entry changed in a way the witness cannot itemise — a
    // body edit, most often.
    if (entity.fields.length === 0 && entity.reinterpreted.length === 0) {
      return entity.entry_changed === "unknown" ? "may have changed" : "changed";
    }
    return "";
  }

  function fieldLine(field: WitnessFieldDrift): string {
    return field.from_mutation ? `${field.label} (from a marker)` : field.label;
  }
</script>

{#if drift.available}
  <div class="drift" role="group" aria-label="Changed since this snapshot">
    {#if !drift.comparable}
      <p class="note">
        This snapshot recorded its context in an older form, so it cannot be compared.
        The prose is unaffected and restores exactly.
      </p>
    {:else}
      <p class="lede">Since this snapshot:</p>
      <ul>
        {#each drift.entities as entity (entity.entity_id)}
          <li class="entity" class:gone={entity.membership === "removed"}>
            <span class="name">{entity.title}</span>
            {#if headline(entity)}<span class="headline">{headline(entity)}</span>{/if}

            {#if entity.fields.length > 0}
              <ul class="fields">
                {#each entity.fields as field (field.field_id)}
                  <li>
                    <span class="label">{fieldLine(field)}</span>
                    <!-- Cool then warm, left to right: the snapshot's value and
                         the scene's. Same rule as the runs, so the two panes of
                         one gesture cannot say opposite things. -->
                    <span class="was">{shown(field.was)}</span>
                    <span class="arrow" aria-hidden="true">→</span>
                    <span class="now">{shown(field.now)}</span>
                  </li>
                {/each}
              </ul>
            {/if}

            {#if entity.reinterpreted.length > 0}
              <ul class="fields">
                {#each entity.reinterpreted as field (field.field_id)}
                  <li>
                    <span class="label">{field.label}</span>
                    <span class="reinterpreted">
                      {#if field.type_was !== field.type_now}
                        is now a {field.type_now} field, not a {field.type_was} one
                      {:else}
                        no longer allows the same values
                      {/if}
                    </span>
                  </li>
                {/each}
              </ul>
            {/if}

            {#if entity.entry_changed === "unknown" && entity.membership === "present"}
              <!-- Degrade coarsely, never corrupt: "unchanged" is a claim, and
                   this is not in a position to make it. -->
              <span class="unknown">its entry may also have changed — unable to tell</span>
            {/if}
          </li>
        {/each}
      </ul>

      {#if drift.truncated}
        <p class="note">
          This scene's context was larger than a snapshot records, so this list may be
          incomplete.
        </p>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .drift {
    padding: 8px 14px 12px;
    border-top: 1px solid var(--divider);
    background: var(--panel);
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .lede {
    margin: 0 0 6px;
    font-weight: 600;
    color: var(--text-2);
  }
  .drift ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .entity + .entity {
    margin-top: 8px;
  }
  .name {
    font-weight: 600;
    color: var(--text);
  }
  /* An entity that has left the scene is named in the snapshot's colour: it is
     a fact about the version being read, not about the scene as it is. */
  .gone .name {
    color: var(--diff-was);
  }
  .headline {
    margin-left: 6px;
  }
  .fields {
    margin-top: 2px;
    padding-left: 14px;
  }
  .fields li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px;
    line-height: 1.6;
  }
  .label {
    color: var(--text-3);
  }
  .label::after {
    content: ":";
  }
  .was {
    color: var(--diff-was);
  }
  .now {
    color: var(--diff-now);
  }
  .arrow {
    color: var(--text-3);
  }
  .reinterpreted,
  .unknown,
  .note {
    color: var(--text-3);
  }
  .unknown {
    display: block;
    padding-left: 14px;
  }
  .note {
    margin: 8px 0 0;
  }
</style>
