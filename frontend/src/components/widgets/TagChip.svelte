<script lang="ts">
  // The luggage-tag chip atom (#247). One silhouette — a smooth rounded body with
  // a right-pointing tip — so a tag reads as its own kind of object, never just
  // another rounded pill. Used by BOTH the editable TagPicker field and the
  // read-only tags render in FieldValueEditor. The shape is an SVG path sized to
  // the chip's measured width (the tip stays a fixed length; only the body grows),
  // which is also what lets it carry a stroke the CSS `clip-path` route can't.
  //
  // Colour is neutral by default and an opt-in governance choice (#247, PR-2): a
  // tag carries no colour until someone spends one on it, so most chips render
  // neutral (var(--inset)) and recede; a coloured tag gets a soft wash of its
  // swatch colour so the few axes the writer scans by pop while the label stays
  // legible. The wash is exposed as the `--tag-fill` / `--tag-stroke` custom
  // props on the chip container — the chip's own per-tag colour sets them inline
  // (per-tag, not a token, via color-mix, which the style-token guard leaves
  // alone), and any external consumer that needs to re-tint (a mutated metadata
  // row) sets the SAME two props rather than reaching into the private SVG path
  // (#705). The default fills come from the props' fallbacks.
  import { getSwatch } from "@/lib/utils/colors";

  interface Props {
    name: string;
    /** A tag not yet in the vocabulary — outlined, "will be created on save". */
    pending?: boolean;
    /** The tag's colour: a palette swatch id, or null/undefined for neutral. */
    color?: string | null;
    /** Show the × at the tip. Editable field only; read-only display omits it. */
    removable?: boolean;
    onRemove?: () => void;
    /** Context for the remove button's aria-label (e.g. the field name). */
    ariaContext?: string;
  }
  let { name, pending = false, color = null, removable = false, onRemove, ariaContext }: Props = $props();

  // A pending tag has no committed colour, so its outline treatment always wins.
  const hex = $derived(!pending && color ? (getSwatch(color)?.hex ?? null) : null);

  const TIP = 11; // fixed tip length in px; the body flexes with the label
  const R = 6; // corner radius on the (left) squared end
  const H = 22; // must match the .tag-chip height below (fixed, so not measured)

  // Only the WIDTH is measured — the height is a CSS constant, so binding it too
  // would add a layout read and make the shape wait for a height pass before first
  // paint. Right-pointing tag: rounded left corners, a single smooth quadratic to
  // the tip at the vertical centre (control point past the right edge so the point
  // reaches ~w-1 without a hard apex). 1px inset keeps a pending stroke visible.
  let w = $state(0);

  const path = $derived(
    w > 0
      ? `M ${1 + R} 1 L ${w - TIP} 1 Q ${w + 7} ${H / 2} ${w - TIP} ${H - 1}` +
          ` L ${1 + R} ${H - 1} Q 1 ${H - 1} 1 ${H - 1 - R} L 1 ${1 + R} Q 1 1 ${1 + R} 1 Z`
      : "",
  );
</script>

<!-- Per-tag colour as a SOFT WASH, not the raw saturated hex: a full-strength
     fill fails contrast under the neutral var(--text-2) label. color-mix with
     transparent is theme-adaptive and inline (so not a style-token). Stroke is a
     stronger mix for a quiet edge. Set as custom props on the container so they
     cascade to the SVG path AND stay overridable by an external tint (#705). -->
<span
  class="tag-chip"
  class:pending
  class:removable
  bind:clientWidth={w}
  style={hex
    ? `--tag-fill: color-mix(in srgb, ${hex} 22%, transparent); --tag-stroke: color-mix(in srgb, ${hex} 55%, transparent)`
    : undefined}
>
  {#if path}
    <svg class="tag-chip-shape" width={w} height={H} viewBox={`0 0 ${w} ${H}`} aria-hidden="true">
      <path d={path} />
    </svg>
  {/if}
  <span class="tag-chip-label">{name}</span>
  {#if removable}
    <button
      class="tag-chip-remove"
      type="button"
      aria-label={ariaContext ? `Remove ${name} from ${ariaContext}` : `Remove ${name}`}
      onmousedown={(e) => e.preventDefault()}
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
    /* Neutral fallbacks; a coloured tag (or an external tint) supplies the props. */
    fill: var(--tag-fill, var(--inset));
    stroke: var(--tag-stroke, var(--border));
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
