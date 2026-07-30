<script lang="ts">
  // The luggage-tag chip atom (#247). One silhouette — a smooth rounded body with
  // a right-pointing tip — so a tag reads as its own kind of object, never just
  // another rounded pill. Used by BOTH the editable TagPicker field and the
  // read-only tags render in FieldValueEditor. The shape is an SVG path sized to
  // the chip's measured width (the tip stays a fixed length; only the body grows),
  // which is also what lets it carry a stroke the CSS `clip-path` route can't.
  //
  // Colour is deliberately NOT here yet: tags are neutral by default and colour is
  // an opt-in governance choice (a following slice), so slice 1 renders neutral
  // (known) and outlined (pending = a tag that will be created on save) only.
  interface Props {
    name: string;
    /** A tag not yet in the vocabulary — outlined, "will be created on save". */
    pending?: boolean;
    /** Show the × at the tip. Editable field only; read-only display omits it. */
    removable?: boolean;
    onRemove?: () => void;
    /** Context for the remove button's aria-label (e.g. the field name). */
    ariaContext?: string;
  }
  let { name, pending = false, removable = false, onRemove, ariaContext }: Props = $props();

  const TIP = 11; // fixed tip length in px; the body flexes with the label
  const R = 6; // corner radius on the (left) squared end

  let w = $state(0);
  let h = $state(0);

  // Right-pointing tag: rounded left corners, a single smooth quadratic to the
  // tip at the vertical centre (control point past the right edge so the point
  // reaches ~w-1 without a hard apex). 1px inset keeps a pending stroke visible.
  const path = $derived(
    w > 0 && h > 0
      ? `M ${1 + R} 1 L ${w - TIP} 1 Q ${w + 7} ${h / 2} ${w - TIP} ${h - 1}` +
          ` L ${1 + R} ${h - 1} Q 1 ${h - 1} 1 ${h - 1 - R} L 1 ${1 + R} Q 1 1 ${1 + R} 1 Z`
      : "",
  );
</script>

<span class="tag-chip" class:pending class:removable bind:clientWidth={w} bind:clientHeight={h}>
  {#if path}
    <svg class="tag-chip-shape" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={path} />
    </svg>
  {/if}
  <span class="tag-chip-label">{name}</span>
  {#if removable}
    <button
      class="tag-chip-remove"
      type="button"
      aria-label={ariaContext ? `Remove ${name} from ${ariaContext}` : `Remove ${name}`}
      onclick={onRemove}
    >×</button>
  {/if}
</span>

<style>
  .tag-chip {
    position: relative;
    display: inline-flex;
    align-items: center;
    box-sizing: border-box;
    height: 22px;
    padding: 0 13px 0 10px;
    font-size: var(--fs-xs);
    line-height: 1;
    color: var(--text-2);
    white-space: nowrap;
  }
  .tag-chip.removable {
    padding-right: 20px;
  }

  .tag-chip-shape {
    position: absolute;
    left: 0;
    top: 0;
    pointer-events: none;
    overflow: visible;
  }
  .tag-chip-shape path {
    fill: var(--inset);
    stroke: var(--border);
    stroke-width: 0.75;
  }

  /* Pending: an uncreated tag reads as an outline, not a solid — honest that it
     doesn't exist in the vocabulary yet. */
  .tag-chip.pending {
    color: var(--accent);
  }
  .tag-chip.pending .tag-chip-shape path {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.2;
    stroke-dasharray: 3 2;
  }

  .tag-chip-label {
    position: relative;
    z-index: 1;
  }

  .tag-chip-remove {
    position: absolute;
    z-index: 2;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 14px;
    height: 14px;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    cursor: pointer;
    opacity: 0.7;
    font-size: var(--fs-sm);
    line-height: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .tag-chip-remove:hover {
    opacity: 1;
  }
</style>
