// Regex-OR matcher.
//
// Single compiled RegExp with sorted-by-length alternation. Apostrophes are
// treated as word-extending characters via lookaround so "Bob" doesn't
// false-match inside "Bob's". Sorting longest-first makes the regex engine
// prefer "Bob's home" over "Bob" at the same start position
// (leftmost-longest with alternation order).

const RE_ESCAPE = /[.*+?^${}()|[\]\\]/g;
function escapeRegex(s) {
  return s.replace(RE_ESCAPE, '\\$&');
}

export class RegexMatcher {
  constructor(flatPatterns) {
    // flatPatterns: [{id, name}, ...] already sorted by name length DESC.
    // Build id lookup keyed by lowercased name.
    this.nameToId = new Map();
    for (const p of flatPatterns) {
      const key = p.name.toLowerCase();
      if (!this.nameToId.has(key)) this.nameToId.set(key, p.id);
    }
    const escaped = flatPatterns.map(p => escapeRegex(p.name));
    // (?<![\w']) and (?![\w']) treat apostrophe as a word-extension so
    // "Bob" doesn't match the prefix of "Bob's". Without these, JS \b
    // would treat ' as a boundary and produce false hits.
    const src = "(?<![\\w'])(" + escaped.join('|') + ")(?![\\w'])";
    this.regex = new RegExp(src, 'gi');
  }

  scan(text) {
    const hits = [];
    this.regex.lastIndex = 0;
    let m;
    while ((m = this.regex.exec(text)) !== null) {
      const matched = m[1];
      const id = this.nameToId.get(matched.toLowerCase());
      hits.push({
        start: m.index,
        end: m.index + matched.length,
        id,
        name: matched,
      });
    }
    return hits;
  }
}
