// Width-aware tag packing (ADR-0066).
//
// The pure core of NodeRow's tag line: given each pill's natural width and the
// width available on the line, decide how many pills show. The DOM/canvas
// measurement that produces those widths lives in NodeRow.svelte; this function
// is deterministic so the packing rules can be unit-tested without a layout.
//
// The rules:
//   - pills fill the line left→right;
//   - if every pill fits, all show and there is no +N chip;
//   - otherwise room is reserved for the +N chip and the pills are re-packed
//     into the smaller budget, keeping at least one pill so a row never reads
//     "+3" with nothing beside it;
//   - if the width is unknown (<= 0, e.g. before first layout / in a test with
//     no measurement), every pill shows — we never hide what we can't prove
//     overflows.

export function packTagLine(
  pillWidths: readonly number[],
  availWidth: number,
  gap: number,
  plusNWidth: number,
): number {
  const n = pillWidths.length;
  if (n === 0) return 0;
  if (availWidth <= 0) return n;

  const fits = (limit: number): number => {
    let used = 0;
    let count = 0;
    for (let i = 0; i < n; i++) {
      const need = (i > 0 ? gap : 0) + pillWidths[i];
      if (used + need > limit) break;
      used += need;
      count++;
    }
    return count;
  };

  if (fits(availWidth) === n) return n;
  // Not all fit: reserve the +N chip's width (plus a gap) and re-pack.
  return Math.max(1, fits(availWidth - plusNWidth - gap));
}
