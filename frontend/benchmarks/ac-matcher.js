// Aho-Corasick matcher.
//
// Standard trie-with-failure-links construction, scanning in O(n + matches).
// Apostrophes are treated as word-extending characters in the boundary
// check (matching the regex matcher's semantics so the two are
// behaviourally equivalent). After scanning we resolve overlapping hits in
// favour of the longest match starting at each position.

function isWordChar(code) {
  // [a-z0-9_'] — apostrophe included so "Bob's" stays a single token.
  // Code points: 0-9 = 48-57, A-Z = 65-90, a-z = 97-122, _ = 95, ' = 39
  return (
    (code >= 97 && code <= 122) ||
    (code >= 65 && code <= 90) ||
    (code >= 48 && code <= 57) ||
    code === 95 ||
    code === 39
  );
}

function isWordBoundary(text, start, end) {
  // start: inclusive index of match start
  // end:   exclusive index of match end
  const before = start === 0 ? -1 : text.charCodeAt(start - 1);
  const after = end >= text.length ? -1 : text.charCodeAt(end);
  if (before !== -1 && isWordChar(before)) return false;
  if (after !== -1 && isWordChar(after)) return false;
  return true;
}

export class AhoCorasickMatcher {
  constructor(flatPatterns) {
    // flatPatterns: [{id, name}, ...]
    this.root = this._newNode();
    for (const p of flatPatterns) {
      this._addPattern(p.name.toLowerCase(), p.id, p.name.length);
    }
    this._buildFailures();
  }

  _newNode() {
    return {
      children: new Map(),
      fail: null,
      // outputs: array of {id, length} for patterns ending here
      outputs: [],
    };
  }

  _addPattern(lowerName, id, length) {
    let node = this.root;
    for (let i = 0; i < lowerName.length; i++) {
      const ch = lowerName[i];
      let next = node.children.get(ch);
      if (!next) {
        next = this._newNode();
        node.children.set(ch, next);
      }
      node = next;
    }
    node.outputs.push({ id, length });
  }

  _buildFailures() {
    const queue = [];
    for (const child of this.root.children.values()) {
      child.fail = this.root;
      queue.push(child);
    }
    while (queue.length) {
      const node = queue.shift();
      for (const [ch, child] of node.children) {
        let fail = node.fail;
        while (fail !== null && !fail.children.has(ch)) {
          fail = fail.fail;
        }
        child.fail = fail ? fail.children.get(ch) || this.root : this.root;
        // Propagate suffix outputs so we don't have to walk fail links
        // at scan time.
        if (child.fail.outputs.length) {
          child.outputs = child.outputs.concat(child.fail.outputs);
        }
        queue.push(child);
      }
    }
  }

  scan(text) {
    const lower = text.toLowerCase();
    const raw = [];
    let node = this.root;
    for (let i = 0; i < lower.length; i++) {
      const ch = lower[i];
      while (node !== this.root && !node.children.has(ch)) {
        node = node.fail;
      }
      const next = node.children.get(ch);
      if (next) {
        node = next;
        for (const out of node.outputs) {
          const start = i - out.length + 1;
          const end = i + 1;
          if (isWordBoundary(text, start, end)) {
            raw.push({ start, end, id: out.id, name: text.slice(start, end) });
          }
        }
      }
    }
    return resolveLongest(raw);
  }
}

// Drop shorter hits that are fully contained in a longer hit sharing the
// same start position. Mirrors the longest-match-wins semantic of the
// regex-OR alternation.
function resolveLongest(hits) {
  if (hits.length <= 1) return hits;
  // Sort by start asc, length desc (longest first at same start)
  hits.sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    return (b.end - b.start) - (a.end - a.start);
  });
  const out = [];
  let lastEnd = -1;
  for (const h of hits) {
    if (h.start < lastEnd) continue; // dominated by an earlier longer match
    out.push(h);
    lastEnd = h.end;
  }
  return out;
}
