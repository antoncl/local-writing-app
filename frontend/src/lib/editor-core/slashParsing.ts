// Pure parsing/filtering helpers for ProseBodyView's slash-command menu.
// No editor or component state — just string → structure transforms, so they
// live here and stay unit-testable. The stateful glue (reading the editor doc,
// positioning the menu, building the command list) stays in the component.

const SLASH_COMMAND_PATTERN = /^[a-zA-Z0-9_-]*$/;
const SLASH_WITH_ARGS_PATTERN = /^([a-zA-Z0-9_-]+)\s+(.*)$/;

/** Split a "/command args" body (the "/" already stripped) into command + raw args. */
export function parseSlashBody(text: string): { command: string; args: string } | null {
  if (SLASH_COMMAND_PATTERN.test(text)) return { command: text, args: "" };
  const m = text.match(SLASH_WITH_ARGS_PATTERN);
  if (m) return { command: m[1], args: m[2] };
  return null;
}

/** Parse a "5x3" / "5×3" table-dimension token, clamped to [1, 100]. */
export function parseTableDims(token: string): { rows: number; cols: number } | null {
  const m = token.match(/^(\d+)\s*[x×]\s*(\d+)$/i);
  if (!m) return null;
  const rows = Math.min(100, Math.max(1, parseInt(m[1], 10)));
  const cols = Math.min(100, Math.max(1, parseInt(m[2], 10)));
  return { rows, cols };
}

/** Tokenize a slash-command argument string, honouring single/double quotes. */
export function tokenizeSlashArgs(input: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  while (i < input.length) {
    while (i < input.length && /\s/.test(input[i])) i++;
    if (i >= input.length) break;
    if (input[i] === '"' || input[i] === "'") {
      const quote = input[i++];
      let token = "";
      while (i < input.length && input[i] !== quote) token += input[i++];
      if (i < input.length) i++;
      tokens.push(token);
    } else {
      let token = "";
      while (i < input.length && !/\s/.test(input[i])) token += input[i++];
      tokens.push(token);
    }
  }
  return tokens;
}

/** Word-prefix match: true if any whitespace-delimited word of `haystack` starts with `needle`. */
export function matchesSlashFilter(haystack: string, needle: string): boolean {
  const lower = needle.toLowerCase();
  return haystack.toLowerCase().split(/\s+/).some((word) => word.startsWith(lower));
}

/**
 * Filter a slash-command list by the typed command text. With args present an
 * exact label match wins; otherwise fall back to prefix-matching label /
 * description / group.
 */
export function filterSlashCommands<T extends { label: string; description: string; group: string }>(
  commands: T[],
  command: string,
  argsPresent: boolean,
): T[] {
  if (!command) return commands;
  const lower = command.toLowerCase();
  if (argsPresent) {
    const exact = commands.filter((cmd) => cmd.label.toLowerCase() === lower);
    if (exact.length > 0) return exact;
  }
  return commands.filter((cmd) =>
    matchesSlashFilter(cmd.label, command) ||
    matchesSlashFilter(cmd.description, command) ||
    matchesSlashFilter(cmd.group, command),
  );
}
