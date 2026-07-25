<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { usePlotBoardContext } from "./plotBoardContext";

  let { data }: { data: { cardId: string } } = $props();

  const getCtx = usePlotBoardContext();
  let ctx = $derived(getCtx());
  let card = $derived(ctx.cardById(data.cardId));
  let cardClaims = $derived(ctx.claimsForCard(data.cardId));
</script>

{#if card}
  <article
    class="plot-card"
    class:selected={ctx.selectedCardId === card.id && !ctx.selectedClaimId}
    class:drag-over={ctx.dragOverCardId === card.id}
    ondragenter={(event) => ctx.allowCardDrop(card.id, event)}
    ondragover={(event) => ctx.allowCardDrop(card.id, event)}
    ondragleave={(event) => ctx.leaveCardDrop(card.id, event)}
    ondrop={(event) => ctx.dropOnCard(card.id, event)}
  >
    <Handle type="target" position={Position.Left} id="in" class="plot-port in" />
    <Handle type="source" position={Position.Right} id="out" class="plot-port out" />

    <header>
      <button type="button" class="card-select nodrag" onclick={() => ctx.selectCard(card.id)}>
        <strong>{card.title}</strong>
      </button>
      {#if card.node_ref}
        <button
          type="button"
          class="open-node nodrag"
          title="Open linked scene"
          aria-label={`Open linked scene for ${card.title}`}
          onclick={(event) => ctx.openCardNode(card, event)}
        ><i class="ti ti-arrow-up-right" aria-hidden="true"></i></button>
      {:else}
        <button
          type="button"
          class="open-node nodrag"
          title="Promote to scene"
          aria-label={`Promote ${card.title} to scene`}
          disabled={ctx.saving}
          onclick={(event) => ctx.promoteCard(card, event)}
        ><i class="ti ti-file-plus" aria-hidden="true"></i></button>
      {/if}
    </header>
    {#if card.synopsis}
      <p>{card.synopsis}</p>
    {/if}
    <div class="claim-chips">
      {#each cardClaims as claim (claim.id)}
        <span
          class="claim-chip nodrag"
          class:selected={claim.id === ctx.selectedClaimId}
          role="group"
          aria-label={`Claim ${ctx.pointLabel(claim)}`}
          draggable={true}
          ondragstart={(event) => ctx.dragClaim(claim, event)}
          ondragend={() => ctx.clearDragOver()}
        >
          <button
            type="button"
            class="claim-chip-main"
            onclick={(event) => {
              event.stopPropagation();
              ctx.selectClaim(claim);
            }}
          >
            <span>{ctx.pointLabel(claim)}</span>
          </button>
          <button
            type="button"
            class="claim-remove"
            title={`Remove ${ctx.pointLabel(claim)}`}
            aria-label={`Remove ${ctx.pointLabel(claim)}`}
            disabled={ctx.saving}
            onclick={(event) => ctx.removeClaim(claim, event)}
          >
            <i class="ti ti-x" aria-hidden="true"></i>
          </button>
        </span>
      {/each}
    </div>
  </article>
{/if}
