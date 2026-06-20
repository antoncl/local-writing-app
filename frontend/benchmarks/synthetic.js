// Synthetic data generators for the matcher benchmark.
// Goal: produce pattern sets and prose that resemble a real writing-app
// project (Honorverse-scale). Deterministic via seeded RNG so runs are
// comparable across machines.

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const FIRST_NAMES = [
  'Honor', 'Hamish', 'Michelle', 'Aivars', 'Aldona', 'Eloise', 'Stephanie',
  'Helen', 'Allison', 'Catherine', 'Theresa', 'Klaus', 'Pavel', 'Rafe',
  'Andrew', 'Erica', 'Beth', 'Manfred', 'Sergei', 'Tomas', 'Anders',
  'Brigitte', 'Solveig', 'Pieter', 'Wenke', 'Lothar', 'Cordelia', 'Miles',
  'Aral', 'Gregor', 'Ekaterin', 'Ivan', 'Bothari', 'Elena', 'Mark',
  'Galeni', 'Quinn', 'Bel', 'Padma', 'Drou', 'Kou', 'Alys',
  'Vidal', 'Vorpatril', 'Byerly', 'Tej', 'Rish', 'Simon', 'Illyan',
  'Negri', 'Vorgustafson', 'Vorgrishnov', 'Vorrutyer', 'Vorbarra',
];

const LAST_NAMES = [
  'Harrington', 'Alexander', 'McKeon', 'Sarnow', 'Cromarty', 'Henke',
  'Brigham', 'Tremaine', 'Aubrey', 'Mayhew', 'Mercier', 'Theisman',
  'Tourville', 'Pritchart', 'Giscard', 'Foraker', 'Bogdanovich', 'Yanakov',
  'Vorkosigan', 'Vorbarra', 'Vorrutyer', 'Vorpatril', 'Vorhalas', 'Vorgrishnov',
  'Naismith', 'Bothari-Jesek', 'Koudelka', 'Vorthys', 'Vorberg',
];

const TITLES_PREFIX = [
  'Lady', 'Lord', 'Duke', 'Duchess', 'Earl', 'Countess', 'Baron', 'Baroness',
  'Admiral', 'Captain', 'Commodore', 'Lieutenant', 'Commander', 'Major',
  'Doctor', 'Professor', 'Master', 'Sir',
];

const PLACE_WORDS = [
  'Manticore', 'Sphinx', 'Gryphon', 'Haven', 'Beowulf', 'Grayson', 'Mesa',
  'Erewhon', 'Andermani', 'Silesia', 'Barrayar', 'Komarr', 'Sergyar',
  'Athos', 'Cetaganda', 'Jackson', 'Escobar', 'Vorbarr-Sultana', 'Hassadar',
  'Vorkosigan-Surleau', 'Solstice', 'Equator', 'Vashnoi', 'Tanery-Base',
];

const PLACE_SUFFIX = [
  'Station', 'Base', 'Outpost', 'Tower', 'Citadel', 'Keep', 'Hold',
  'District', 'Quarter', 'Compound', 'Estate', 'Manor', 'House', 'Tower',
];

const APOSTROPHE_NAMES = [
  "O'Brien", "O'Connor", "O'Reilly", "D'Angelo", "M'Bantu", "N'Goro",
  "T'sori", "K'amaal", "Sa'gar", "Ven'tar",
];

const FILLER_WORDS = (
  "the and of to in a was that had he she his her him with for on by " +
  "as at from but not it is were said could would been have has " +
  "into through about when where which who whose if then than so " +
  "before after under over against between among through during while " +
  "again further once here there all any both each few more most other some " +
  "such only own same than too very can will just should now"
).split(/\s+/);

const SENTENCE_STARTERS = [
  'When', 'After', 'Before', 'While', 'Although', 'Because', 'If', 'Since',
  'As', 'Until', 'However', 'Moreover', 'Furthermore', 'Nonetheless',
];

function pick(arr, rng) {
  return arr[Math.floor(rng() * arr.length)];
}

// Generate `n` patterns with the requested mix:
//   60% single-word (first name, last name, or place word)
//   30% multi-word (title + name, first + last, place + suffix)
//   10% apostrophe-containing
// Each gets 0-3 aliases drawn from the same pools.
export function generatePatterns(n, seed = 1) {
  const rng = mulberry32(seed);
  const patterns = [];
  const seen = new Set();

  let i = 0;
  while (patterns.length < n) {
    const roll = rng();
    let name;
    if (roll < 0.6) {
      const which = rng();
      if (which < 0.4) name = pick(FIRST_NAMES, rng);
      else if (which < 0.75) name = pick(LAST_NAMES, rng);
      else name = pick(PLACE_WORDS, rng);
    } else if (roll < 0.9) {
      const which = rng();
      if (which < 0.4) name = pick(TITLES_PREFIX, rng) + ' ' + pick(LAST_NAMES, rng);
      else if (which < 0.75) name = pick(FIRST_NAMES, rng) + ' ' + pick(LAST_NAMES, rng);
      else name = pick(PLACE_WORDS, rng) + ' ' + pick(PLACE_SUFFIX, rng);
    } else {
      name = pick(APOSTROPHE_NAMES, rng);
    }
    // Tag with a disambiguator if we'd collide
    const key = name.toLowerCase();
    if (seen.has(key)) {
      name = name + ' ' + (i + 1);
    }
    seen.add(name.toLowerCase());

    const aliasCount = Math.floor(rng() * 4);
    const aliases = [];
    for (let a = 0; a < aliasCount; a++) {
      let alias;
      const which = rng();
      if (which < 0.5) alias = pick(FIRST_NAMES, rng);
      else if (which < 0.85) alias = pick(LAST_NAMES, rng);
      else alias = pick(APOSTROPHE_NAMES, rng);
      const aliasKey = alias.toLowerCase();
      if (aliasKey !== key && !aliases.some(x => x.toLowerCase() === aliasKey)) {
        aliases.push(alias);
      }
    }

    patterns.push({ id: `entity_${i}`, canonical: name, aliases });
    i++;
  }
  return patterns;
}

// Flatten patterns into a {id, name} pair list — the form matchers consume.
// Sort by length DESC so regex-OR alternation gives longest-match-wins.
export function flattenPatterns(patterns) {
  const flat = [];
  for (const p of patterns) {
    flat.push({ id: p.id, name: p.canonical });
    for (const a of p.aliases) flat.push({ id: p.id, name: a });
  }
  flat.sort((a, b) => b.name.length - a.name.length);
  return flat;
}

// Generate ~`bytes` characters of prose. Every ~hitEvery words we
// inject a randomly-chosen pattern name; the rest is filler words
// arranged into short sentences. Returns the text.
export function generateText(patterns, bytes, seed = 2, hitEvery = 80) {
  const rng = mulberry32(seed);
  const out = [];
  let totalLen = 0;
  let wordsSinceHit = 0;
  let sentenceLen = 0;
  let firstInSentence = true;
  let needPeriod = false;

  while (totalLen < bytes) {
    let word;
    const injectHit = wordsSinceHit >= hitEvery + Math.floor(rng() * 40) - 20;
    if (injectHit) {
      const p = pick(patterns, rng);
      // 70% canonical, 30% alias if available
      if (p.aliases.length && rng() < 0.3) {
        word = pick(p.aliases, rng);
      } else {
        word = p.canonical;
      }
      wordsSinceHit = 0;
    } else {
      word = firstInSentence ? pick(SENTENCE_STARTERS, rng) : pick(FILLER_WORDS, rng);
      wordsSinceHit++;
    }

    if (firstInSentence) {
      word = word.charAt(0).toUpperCase() + word.slice(1);
      firstInSentence = false;
    }
    out.push(word);
    totalLen += word.length + 1;
    sentenceLen++;

    // End sentences periodically
    if (sentenceLen > 8 + Math.floor(rng() * 12)) {
      needPeriod = true;
      sentenceLen = 0;
      firstInSentence = true;
    }

    if (needPeriod) {
      out[out.length - 1] += '.';
      needPeriod = false;
    }
  }
  return out.join(' ');
}

// Extract a window of `windowChars` characters around a random position
// in `text`. Used for per-keystroke scan measurement.
export function randomWindow(text, windowChars, rng) {
  if (text.length <= windowChars) return { start: 0, end: text.length, text };
  const start = Math.floor(rng() * (text.length - windowChars));
  const end = start + windowChars;
  return { start, end, text: text.slice(start, end) };
}

export { mulberry32 };
