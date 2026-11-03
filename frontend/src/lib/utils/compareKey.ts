// The A / S / B version keys of the read-only reviews (snapshot compare, proposal
// review): the bare letter, or Alt+letter so the same chord works as in a line-edit
// review (#2530). Returns the lower-case letter, or null when the press is not one.
export function compareKey(event: KeyboardEvent): "a" | "s" | "b" | null {
  if (event.ctrlKey || event.metaKey) return null;
  if (!event.altKey) return /^[asb]$/i.test(event.key) ? (event.key.toLowerCase() as "a" | "s" | "b") : null;
  if (event.shiftKey) return null;
  // The letter on the key first (AZERTY, Dvorak); the key's position only when
  // Alt turns the letter into another character (macOS: å ß ∫) - as lineEditSuggestions.
  const letter = /^[a-z]$/i.test(event.key)
    ? event.key.toLowerCase()
    : /^Key[ASB]$/.test(event.code) ? event.code.slice(3).toLowerCase() : "";
  return letter === "a" || letter === "s" || letter === "b" ? letter : null;
}
