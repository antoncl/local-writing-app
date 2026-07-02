import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});

turndown.use(gfm);
turndown.addRule("todoAnchor", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.todoId);
  },
  replacement: (content: string, node: Node) => {
    const element = node as HTMLElement;
    const todoId = element.dataset.todoId;
    if (!todoId) return content;
    const status = element.dataset.todoStatus === "done" ? "done" : "open";
    const note = encodeURIComponent(element.dataset.todoNote ?? "");
    return `<!-- embedded-todo:id=${todoId};status=${status};note=${note} -->${content}<!-- /embedded-todo -->`;
  },
});
turndown.addRule("characterMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.character);
  },
  replacement: (content: string, node: Node) => {
    const element = node as HTMLElement;
    const id = element.dataset.character;
    if (!id) return content;
    return `<!-- character:id=${id} -->${content}<!-- /character -->`;
  },
});
turndown.addRule("mutationMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.mutationEntity);
  },
  replacement: (_content: string, node: Node) => {
    const element = node as HTMLElement;
    const entity = element.dataset.mutationEntity;
    const markerId = element.dataset.mutationId;
    if (!entity || !markerId) return "";
    // A pill is a mutation unit (#69, ADR-0016): its rows serialize to the
    // single-line marker when there is one (head folded into the sole row —
    // v1.0/v1.1 markers stay byte-stable) and to the multi-line carrier
    // comment when there are more. Values/names are url-encoded so they
    // survive the markdown round-trip; optional op/name/group are emitted only
    // when non-default, in canonical order (mirrors lore_mutations).
    const rows = mutationRowsFromElement(element);
    if (rows.length === 0) return "";
    const name = element.dataset.mutationName ?? "";
    if (rows.length === 1) {
      const row = rows[0];
      const group = element.dataset.mutationGroup ?? "";
      const parts = [`entity=${entity}`, `field=${row.field}`];
      if (row.op && row.op !== "replace") parts.push(`op=${row.op}`);
      parts.push(`value=${encodeURIComponent(row.value)}`);
      if (name) parts.push(`name=${encodeURIComponent(name)}`);
      if (group) parts.push(`group=${group}`);
      parts.push(`id=${row.id || markerId}`);
      return `<!-- mutate:${parts.join(";")} -->`;
    }
    const head = [`entity=${entity}`];
    if (name) head.push(`name=${encodeURIComponent(name)}`);
    head.push(`id=${markerId}`);
    const lines = rows.map((row) => {
      const parts = [`field=${row.field}`];
      if (row.op && row.op !== "replace") parts.push(`op=${row.op}`);
      parts.push(`value=${encodeURIComponent(row.value)}`);
      parts.push(`id=${row.id}`);
      return parts.join(";");
    });
    return `<!-- mutate:${head.join(";")}\n${lines.join("\n")}\n-->`;
  },
});
turndown.addRule("mutationCloseMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.mutationCloseRef);
  },
  replacement: (_content: string, node: Node) => {
    const element = node as HTMLElement;
    const ref = element.dataset.mutationCloseRef;
    const markerId = element.dataset.mutationId;
    if (!ref || !markerId) return "";
    return `<!-- mutate:close;ref=${ref};id=${markerId} -->`;
  },
});
turndown.addRule("simpleMarkdownTable", {
  filter: "table",
  replacement: (_content: string, node: Node) => {
    const table = node as HTMLTableElement;
    const cellRows = Array.from(table.rows);
    if (cellRows.length === 0) return "";

    const textRows = cellRows.map((row) =>
      Array.from(row.cells).map((cell) => cleanTableCell(turndown.turndown(cell.innerHTML))),
    );
    const columnCount = Math.max(...textRows.map((row) => row.length));
    if (columnCount === 0) return "";

    const alignments = Array.from({ length: columnCount }, (_, colIndex) => {
      for (const row of cellRows) {
        const cell = row.cells[colIndex] as HTMLElement | undefined;
        if (!cell) continue;
        const value = (cell.style.textAlign || cell.getAttribute("align") || "").toLowerCase();
        if (value) return value;
      }
      return "";
    });

    const normalizedRows = textRows.map((row) => padRow(row, columnCount));
    const header = normalizedRows[0];
    const bodyRows = normalizedRows.slice(1);
    const separator = alignments.map((align) => {
      if (align === "center") return ":---:";
      if (align === "right") return "---:";
      if (align === "left") return ":---";
      return "---";
    });
    const markdownRows = [header, separator, ...bodyRows].map(formatTableRow);

    return `\n\n${markdownRows.join("\n")}\n\n`;
  },
});

export async function sceneMarkdownToHtml(markdown: string): Promise<string> {
  const prepared = markEmbeddedMutationCloses(
    markEmbeddedMutations(markEmbeddedCharacters(markEmbeddedTodos(markdown || ""))),
  );
  return (await marked.parse(prepared)) || "<p></p>";
}

export function editorHtmlToSceneMarkdown(html: string): string {
  return turndown.turndown(html).trim();
}

function padRow(row: string[], columnCount: number): string[] {
  return [...row, ...Array.from({ length: columnCount - row.length }, () => "")];
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function cleanTableCell(value: string): string {
  return value.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();
}

function markEmbeddedTodos(markdown: string): string {
  const migrated = markdown.replace(
    /<!--\s*todo-anchor:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*\/todo-anchor\s*-->/g,
    (_match, todoId: string, content: string) => {
      return `<span data-todo-id="${escapeAttribute(todoId)}" data-todo-status="open" data-todo-note="">${content}</span>`;
    },
  );

  return migrated.replace(
    /<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^]*?)\s*-->([\s\S]*?)<!--\s*\/embedded-todo\s*-->/g,
    (_match, todoId: string, status: string, note: string, content: string) => {
      return `<span data-todo-id="${escapeAttribute(todoId)}" data-todo-status="${status}" data-todo-note="${escapeAttribute(decodeNote(note))}">${content}</span>`;
    },
  );
}

function markEmbeddedCharacters(markdown: string): string {
  return markdown.replace(
    /<!--\s*character:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*\/character\s*-->/g,
    (_match, characterId: string, content: string) => {
      return `<span data-character="${escapeAttribute(characterId)}">${content}</span>`;
    },
  );
}

interface MutationRowShape {
  id: string;
  field: string;
  op: string;
  value: string;
}

/** Read a mutation pill span's rows: the JSON `data-mutation-rows` attr (#69),
 *  falling back to the pre-#69 one-field-per-span shape for pasted HTML. */
function mutationRowsFromElement(element: HTMLElement): MutationRowShape[] {
  const raw = element.dataset.mutationRows;
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map((row) => ({
          id: String(row?.id ?? ""),
          field: String(row?.field ?? ""),
          op: String(row?.op || "replace"),
          value: String(row?.value ?? ""),
        }));
      }
    } catch {
      // fall through to the legacy shape
    }
  }
  const field = element.dataset.mutationField;
  if (!field) return [];
  return [
    {
      id: element.dataset.mutationId ?? "",
      field,
      op: element.dataset.mutationOp || "replace",
      value: element.dataset.mutationValue ?? "",
    },
  ];
}

function mutationSpan(
  entity: string,
  name: string,
  group: string,
  unitId: string,
  rows: MutationRowShape[],
): string {
  const nameAttr = name ? ` data-mutation-name="${escapeAttribute(name)}"` : "";
  const groupAttr = group ? ` data-mutation-group="${escapeAttribute(group)}"` : "";
  return (
    `<span data-mutation-entity="${escapeAttribute(entity)}"` +
    nameAttr +
    groupAttr +
    ` data-mutation-rows="${escapeAttribute(JSON.stringify(rows))}"` +
    ` data-mutation-id="${escapeAttribute(unitId)}"></span>`
  );
}

// One field row of a carrier comment (#69) — mirrors the backend's
// MUTATION_CARRIER_ROW_PATTERN; keep in lockstep with lore_mutations.py.
const CARRIER_ROW_PATTERN =
  /^field=([A-Za-z0-9_.-]+);(?:op=(add|remove|replace);)?value=([^;\s]*);id=([A-Za-z0-9_-]+)$/;

function markEmbeddedMutations(markdown: string): string {
  // A mutation marker is a self-contained point comment (no wrapped prose) →
  // an empty atom span the MutationMark node parses. Values/names are
  // url-decoded into the data attributes for display; turndown re-encodes them
  // on save. Two grammars (#69, ADR-0016): the multi-line carrier (one unit,
  // N field rows) runs first — its head can never match the single-line form —
  // then the single-line marker, loaded as a one-row unit whose unit id IS the
  // marker id. A carrier with any malformed row is left as an inert comment
  // (mirrors the backend: rewrites must never drop a hand-authored line).
  const withCarriers = markdown.replace(
    /<!--[ \t]*mutate:entity=([A-Za-z0-9_-]+)(?:;name=([^;\s]*))?;id=([A-Za-z0-9_-]+)[ \t]*\r?\n((?:[ \t]*field=[^\r\n]*\r?\n)+)[ \t]*-->/g,
    (match, entity: string, name: string | undefined, unitId: string, rowsBlock: string) => {
      const rows: MutationRowShape[] = [];
      for (const line of rowsBlock.split(/\r?\n/)) {
        const text = line.trim();
        if (!text) continue;
        const row = CARRIER_ROW_PATTERN.exec(text);
        if (!row) return match;
        rows.push({ id: row[4], field: row[1], op: row[2] || "replace", value: decodeNote(row[3]) });
      }
      if (rows.length === 0) return match;
      return mutationSpan(entity, decodeNote(name ?? ""), "", unitId, rows);
    },
  );
  return withCarriers.replace(
    /<!--\s*mutate:entity=([A-Za-z0-9_-]+);field=([A-Za-z0-9_.-]+);(?:op=(add|remove|replace);)?value=([^;\s]*)(?:;name=([^;\s]*))?(?:;group=([A-Za-z0-9_-]+))?;id=([A-Za-z0-9_-]+)\s*-->/g,
    (
      _match,
      entity: string,
      field: string,
      op: string | undefined,
      value: string,
      name: string | undefined,
      group: string | undefined,
      markerId: string,
    ) => {
      const rows: MutationRowShape[] = [
        { id: markerId, field, op: op || "replace", value: decodeNote(value) },
      ];
      return mutationSpan(entity, decodeNote(name ?? ""), group ?? "", markerId, rows);
    },
  );
}

function markEmbeddedMutationCloses(markdown: string): string {
  // Interval-close marker (#59): a self-contained point comment → empty atom span
  // the MutationClose node parses. Distinct grammar (close;ref=) from a start
  // marker, so this runs after markEmbeddedMutations without overlap.
  return markdown.replace(
    /<!--\s*mutate:close;ref=([A-Za-z0-9_-]+);id=([A-Za-z0-9_-]+)\s*-->/g,
    (_match, ref: string, markerId: string) => {
      return (
        `<span data-mutation-close-ref="${escapeAttribute(ref)}"` +
        ` data-mutation-id="${escapeAttribute(markerId)}"></span>`
      );
    },
  );
}

function decodeNote(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
