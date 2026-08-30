// Direction of a metadata-field-definition move between inheritance layers
// (#1677, follow-up to #1667). The layer chain is ordered farthest-ancestor
// first, the project-local layer last, so a "downward" move — to a layer LATER
// in the chain (nearer / more local) — narrows the field's visibility: it
// leaves the farther layer, so projects that inherited it there (including
// sibling projects the open project can't see) lose the field and any values
// they set for it are hidden. An "upward" move only widens visibility and is
// harmless. Only the downward case warrants a warning.

export function isDownwardLayerMove(
  layers: readonly { id: string }[],
  sourceLayerId: string,
  targetLayerId: string,
): boolean {
  const sourceIndex = layers.findIndex((layer) => layer.id === sourceLayerId);
  const targetIndex = layers.findIndex((layer) => layer.id === targetLayerId);
  // Warn only when we're sure it's downward — an unresolvable position (both
  // should always resolve for an owned field + a picked target) declines to
  // warn rather than firing a spurious modal.
  if (sourceIndex < 0 || targetIndex < 0) return false;
  return targetIndex > sourceIndex;
}
