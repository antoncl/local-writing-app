/**
 * `difflib.SequenceMatcher` (`isjunk` supported; `autojunk` is always False,
 * as the backend uses it) — extracted from `snapshotDiff.ts` (ADR-0096 §3, S2)
 * so `sequenceAlign.ts` can build both the body's block alignment and a plain
 * item-index alignment on the same matcher, unchanged.
 */
export type IsJunk = ((s: string) => boolean) | null;

export class SequenceMatcher {
  private a: string[];
  private b: string[];
  private isjunk: IsJunk;
  private b2j = new Map<string, number[]>();
  private bjunk = new Set<string>();
  private matchingBlocks: [number, number, number][] | null = null;
  private fullbcount: Map<string, number> | null = null;

  constructor(isjunk: IsJunk, a: string[], b: string[]) {
    this.isjunk = isjunk;
    this.a = a;
    this.b = b;
    this.chainB();
  }

  private chainB(): void {
    const b2j = new Map<string, number[]>();
    for (let i = 0; i < this.b.length; i++) {
      const elt = this.b[i];
      const arr = b2j.get(elt);
      if (arr) arr.push(i);
      else b2j.set(elt, [i]);
    }
    const bjunk = new Set<string>();
    if (this.isjunk) {
      for (const elt of b2j.keys()) if (this.isjunk(elt)) bjunk.add(elt);
      for (const elt of bjunk) b2j.delete(elt);
    }
    // autojunk = False: no popular-element pruning.
    this.b2j = b2j;
    this.bjunk = bjunk;
  }

  private isbjunk(elt: string): boolean {
    return this.bjunk.has(elt);
  }

  findLongestMatch(alo: number, ahi: number, blo: number, bhi: number): [number, number, number] {
    const { a, b, b2j } = this;
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
    let j2len = new Map<number, number>();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map<number, number>();
      const js = b2j.get(a[i]);
      if (js) {
        for (const j of js) {
          if (j < blo) continue;
          if (j >= bhi) break;
          const k = (j2len.get(j - 1) ?? 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) {
            besti = i - k + 1;
            bestj = j - k + 1;
            bestsize = k;
          }
        }
      }
      j2len = newj2len;
    }
    while (besti > alo && bestj > blo && !this.isbjunk(b[bestj - 1]) && a[besti - 1] === b[bestj - 1]) {
      besti--;
      bestj--;
      bestsize++;
    }
    while (
      besti + bestsize < ahi &&
      bestj + bestsize < bhi &&
      !this.isbjunk(b[bestj + bestsize]) &&
      a[besti + bestsize] === b[bestj + bestsize]
    ) {
      bestsize++;
    }
    while (besti > alo && bestj > blo && this.isbjunk(b[bestj - 1]) && a[besti - 1] === b[bestj - 1]) {
      besti--;
      bestj--;
      bestsize++;
    }
    while (
      besti + bestsize < ahi &&
      bestj + bestsize < bhi &&
      this.isbjunk(b[bestj + bestsize]) &&
      a[besti + bestsize] === b[bestj + bestsize]
    ) {
      bestsize++;
    }
    return [besti, bestj, bestsize];
  }

  getMatchingBlocks(): [number, number, number][] {
    if (this.matchingBlocks) return this.matchingBlocks;
    const la = this.a.length;
    const lb = this.b.length;
    const queue: [number, number, number, number][] = [[0, la, 0, lb]];
    const matching: [number, number, number][] = [];
    while (queue.length) {
      const [alo, ahi, blo, bhi] = queue.pop()!;
      const [i, j, k] = this.findLongestMatch(alo, ahi, blo, bhi);
      if (k) {
        matching.push([i, j, k]);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    matching.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]);
    const nonAdjacent: [number, number, number][] = [];
    let i1 = 0;
    let j1 = 0;
    let k1 = 0;
    for (const [i2, j2, k2] of matching) {
      if (i1 + k1 === i2 && j1 + k1 === j2) {
        k1 += k2;
      } else {
        if (k1) nonAdjacent.push([i1, j1, k1]);
        i1 = i2;
        j1 = j2;
        k1 = k2;
      }
    }
    if (k1) nonAdjacent.push([i1, j1, k1]);
    nonAdjacent.push([la, lb, 0]);
    this.matchingBlocks = nonAdjacent;
    return nonAdjacent;
  }

  getOpcodes(): [string, number, number, number, number][] {
    const answer: [string, number, number, number, number][] = [];
    let i = 0;
    let j = 0;
    for (const [ai, bj, size] of this.getMatchingBlocks()) {
      let tag = "";
      if (i < ai && j < bj) tag = "replace";
      else if (i < ai) tag = "delete";
      else if (j < bj) tag = "insert";
      if (tag) answer.push([tag, i, ai, j, bj]);
      i = ai + size;
      j = bj + size;
      if (size) answer.push(["equal", ai, i, bj, j]);
    }
    return answer;
  }

  ratio(): number {
    let matches = 0;
    for (const mb of this.getMatchingBlocks()) matches += mb[2];
    const T = this.a.length + this.b.length;
    return T ? (2.0 * matches) / T : 1.0;
  }

  quickRatio(): number {
    if (!this.fullbcount) {
      const c = new Map<string, number>();
      for (const elt of this.b) c.set(elt, (c.get(elt) ?? 0) + 1);
      this.fullbcount = c;
    }
    const avail = new Map<string, number>();
    let matches = 0;
    for (const elt of this.a) {
      const numb = avail.has(elt) ? avail.get(elt)! : (this.fullbcount.get(elt) ?? 0);
      avail.set(elt, numb - 1);
      if (numb > 0) matches++;
    }
    const T = this.a.length + this.b.length;
    return T ? (2.0 * matches) / T : 1.0;
  }
}
