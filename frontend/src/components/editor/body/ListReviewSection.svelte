<script lang="ts">
  // One `list` field's per-item review (ADR-0096 §6/§7, S3): the section that
  // sits in `EntryRevisionReview`'s flip stack, after the body and the
  // `long_text` flips. Renders the §5 sequence — unchanged items quiet, an
  // edited item's changed members as regions, an addition/removal as one
  // stacked block, the order (while unsettled) at the head — and reports each
  // click straight to the controller's `settleListUnit` (never a local
  // write); the controller composes and writes the list on Done.
  //
  // *Both* is interactive (every unit a region, ADR-0044 §I); *Current*/
  // *Proposed* are plain reads of L/O with every settled unit already merged
  // in — built by reusing `composeList` itself with the undecided units
  // defaulted to declined (Current) or adopted (Proposed), so a version read
  // can never disagree with what a settled unit will actually save.
  import RevisionFlip from "@/components/editor/body/RevisionFlip.svelte";
  import RunFlip from "@/components/editor/body/RunFlip.svelte";
  import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { composeList, listSequence, type ListPairing, type ListResolution, type ListUnit } from "@/lib/utils/listCompare";
  import { visibleItemMembers } from "@/lib/editor-core/listItemIdentity";
  import { itemMarkdown, itemTitle, memberDisplayText, orderMarkdown } from "@/lib/utils/listReviewText";
  import type { DiffRun, DiffView, GroupMember, MetadataFieldDefinition, MetadataValue } from "@/lib/types";

  let {
    field,
    label,
    pairing,
    units,
    L,
    O,
    resolution,
    view,
    resolveTitle = undefined,
    adoptable = true,
    onSettleUnit,
  }: {
    field: MetadataFieldDefinition;
    /** The field's label — the section heading. */
    label: string;
    pairing: ListPairing;
    units: ListUnit[];
    L: MetadataValue[];
    O: MetadataValue[];
    /** This field's running resolution — `EntryProposalController.listResolutions[fieldId]`. */
    resolution: Record<string, true | string | false>;
    view: DiffView;
    resolveTitle?: (id: string) => string | null;
    /** False at an override layer (ADR-0096 §6): shown, nothing clickable. */
    adoptable?: boolean;
    onSettleUnit: (unitKey: string, value: true | string | false) => void;
  } = $props();

  const orderUnit = $derived(units.find((u) => u.kind === "order") ?? null);
  const orderSettled = $derived(orderUnit ? orderUnit.key in resolution : false);
  const orderAdopted = $derived(resolution.order === true);

  function itemRecordOf(list: MetadataValue[], index: number): Record<string, MetadataValue> {
    const item = list[index];
    if (field.item_scalar) return { value: item ?? null };
    return item !== null && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, MetadataValue>) : {};
  }

  function memberOf(key: string): GroupMember | undefined {
    return visibleItemMembers(field).find((m) => m.key === key);
  }

  // ---- Current / Proposed: a plain read, settled units already merged in --
  function effectiveResolution(defaultAdopt: boolean): ListResolution {
    const out: ListResolution = {};
    for (const unit of units) {
      const settled = resolution[unit.key];
      out[unit.key] = settled !== undefined ? settled : defaultAdopt;
    }
    return out;
  }

  const singleVersionMarkdown = $derived.by((): string | null => {
    let arr: MetadataValue[] | null = null;
    if (view === "now") arr = composeList(field, L, O, pairing, effectiveResolution(false));
    else if (view === "was") arr = composeList(field, L, O, pairing, effectiveResolution(true));
    if (!arr) return null;
    return arr.map((item, index) => itemMarkdown(field, item, index, resolveTitle)).join("\n\n") || "*(empty)*";
  });

  // ---- Both: the §5 sequence, one row per entry -----------------------------
  const rows = $derived(view === "both" ? listSequence(pairing, orderAdopted) : []);

  function pairFor(l: number, o: number) {
    return pairing.pairs.find((p) => p.l === l && p.o === o);
  }

  function memberRuns(member: GroupMember, lValue: MetadataValue | undefined, oValue: MetadataValue | undefined): DiffRun[] {
    return [
      { kind: "was", text: memberDisplayText(member, oValue), stacked: true },
      { kind: "now", text: memberDisplayText(member, lValue), stacked: true },
    ];
  }

  /** A settled member's markdown: the region-resolved text for a `long_text`
   *  member (already prose, unescaped), else the chosen side's escaped
   *  display text. Shared by *Both*'s settled row and the single-version
   *  read (via `composeList`/`itemMarkdown`, which reads this same shape). */
  function settledMemberMarkdown(member: GroupMember, settled: true | string | false, lValue: MetadataValue | undefined, oValue: MetadataValue | undefined): string {
    if (member.type === "long_text") {
      if (typeof settled === "string") return settled;
      const raw = settled === true ? oValue : lValue;
      return typeof raw === "string" ? raw : String(raw ?? "");
    }
    if (typeof settled === "string") return settled;
    return memberDisplayText(member, settled === true ? oValue : lValue, resolveTitle);
  }
</script>

<div class="list-review-section">
  <div class="flip-label">{label}</div>
  {#if view === "both"}
    {#if orderUnit && !orderSettled}
      {@const oTitles = [...pairing.pairs].sort((a, b) => a.o - b.o).map((p, i) => itemTitle(field, O[p.o], i))}
      {@const lTitles = [...pairing.pairs].sort((a, b) => a.l - b.l).map((p, i) => itemTitle(field, L[p.l], i))}
      <div class="lrs-unit lrs-order">
        <RunFlip
          {adoptable}
          label={`${label} order`}
          {view}
          runs={[
            { kind: "was", text: orderMarkdown(oTitles), stacked: true },
            { kind: "now", text: orderMarkdown(lTitles), stacked: true },
          ]}
          onSettle={(adopted) => onSettleUnit("order", adopted)}
        />
      </div>
    {/if}
    {#each rows as row, rowIndex (row.kind === "paired" ? `p|${row.l}|${row.o}` : row.kind === "add" ? `add|${row.o}` : `rm|${row.l}`)}
      {#if row.kind === "paired"}
        {@const pair = pairFor(row.l, row.o)}
        {#if pair && pair.edited}
          <div class="lrs-item lrs-edited">
            <div class="lrs-item-title">{itemTitle(field, L[pair.l], rowIndex)}</div>
            {#each pair.members as memberKey (memberKey)}
              {@const member = memberOf(memberKey)}
              {#if member}
                {@const unitKey = `m|${pair.l}|${memberKey}`}
                {@const lRecord = itemRecordOf(L, pair.l)}
                {@const oRecord = itemRecordOf(O, pair.o)}
                {@const settled = resolution[unitKey]}
                <div class="lrs-member">
                  {#if member.type === "long_text"}
                    <!-- A prose member stays in its RevisionFlip for the whole review: its
                         regions settle one by one there (ADR-0096 §4), and the flip carries
                         the member's name as its own label. -->
                    <RevisionFlip
                      {adoptable}
                      currentText={typeof lRecord[member.key] === "string" ? (lRecord[member.key] as string) : ""}
                      proposedText={typeof oRecord[member.key] === "string" ? (oRecord[member.key] as string) : ""}
                      label={member.name || member.key}
                      {view}
                      onResolved={(v) => onSettleUnit(unitKey, v ?? false)}
                    />
                  {:else if settled !== undefined}
                    <div class="lrs-member-name">{member.name || member.key}</div>
                    <!-- Settled: its side, without a clickable region (§4). -->
                    {#await sceneMarkdownToHtml(settledMemberMarkdown(member, settled, lRecord[member.key], oRecord[member.key])) then html}
                      <div class="lrs-settled prose-column">{@html html}</div>
                    {/await}
                  {:else}
                    <div class="lrs-member-name">{member.name || member.key}</div>
                    <RunFlip
                      {adoptable}
                      label={member.name || member.key}
                      {view}
                      runs={memberRuns(member, lRecord[member.key], oRecord[member.key])}
                      onSettle={(adopted) => onSettleUnit(unitKey, adopted)}
                    />
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
        {:else}
          <div class="lrs-item lrs-quiet">{itemTitle(field, L[row.l], rowIndex)}</div>
        {/if}
      {:else if row.kind === "add"}
        {@const unitKey = `add|${row.o}`}
        {@const settled = resolution[unitKey]}
        <div class="lrs-unit lrs-add">
          {#if settled === true}
            {#await sceneMarkdownToHtml(itemMarkdown(field, O[row.o], row.o, resolveTitle)) then html}
              <div class="lrs-settled-block">{@html html}</div>
            {/await}
          {:else}
            <RunFlip
              {adoptable}
              label={`Added: ${itemTitle(field, O[row.o], rowIndex)}`}
              {view}
              runs={[{ kind: "was", text: itemMarkdown(field, O[row.o], row.o, resolveTitle), stacked: true }]}
              onSettle={(adopted) => onSettleUnit(unitKey, adopted)}
            />
          {/if}
        </div>
      {:else}
        {@const unitKey = `rm|${row.l}`}
        {@const settled = resolution[unitKey]}
        <div class="lrs-unit lrs-remove">
          <!-- An adopted removal (settled true) drops out of the sequence
               entirely — the same collapse-to-nothing `adoptRegion` gives the
               body's own accepted deletion. -->
          {#if settled !== true}
            <RunFlip
              {adoptable}
              label={`Removed: ${itemTitle(field, L[row.l], rowIndex)}`}
              {view}
              runs={[{ kind: "now", text: itemMarkdown(field, L[row.l], row.l, resolveTitle), stacked: true }]}
              onSettle={(adopted) => onSettleUnit(unitKey, adopted)}
            />
          {/if}
        </div>
      {/if}
    {/each}
  {:else}
    {#await sceneMarkdownToHtml(singleVersionMarkdown ?? "") then html}
      <div class="lrs-single prose-column">{@html html}</div>
    {/await}
  {/if}
</div>

<style>
  .list-review-section {
    display: flex;
    flex-direction: column;
    flex: none;
  }
  .flip-label {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
    padding: 8px 24px 2px;
  }
  .lrs-item,
  .lrs-unit {
    padding: 2px 24px;
  }
  .lrs-quiet {
    color: var(--text-2);
    font-size: var(--fs-md);
    padding-block: 4px;
  }
  .lrs-item-title {
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text);
    padding-top: 6px;
  }
  .lrs-member {
    padding: 2px 0 2px 12px;
  }
  .lrs-member-name {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .lrs-settled,
  .lrs-settled-block {
    color: var(--text);
  }
  .lrs-single {
    padding: 4px 24px 12px;
  }
</style>
