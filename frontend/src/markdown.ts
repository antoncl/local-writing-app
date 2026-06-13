import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});

turndown.use(gfm);
turndown.addRule("simpleMarkdownTable", {
  filter: "table",
  replacement: (_content: string, node: Node) => {
    const table = node as HTMLTableElement;
    const rows = Array.from(table.rows).map((row) =>
      Array.from(row.cells).map((cell) => cleanTableCell(turndown.turndown(cell.innerHTML))),
    );
    if (rows.length === 0) return "";

    const columnCount = Math.max(...rows.map((row) => row.length));
    if (columnCount === 0) return "";

    const normalizedRows = rows.map((row) => padRow(row, columnCount));
    const header = normalizedRows[0];
    const bodyRows = normalizedRows.slice(1);
    const separator = Array.from({ length: columnCount }, () => "---");
    const markdownRows = [header, separator, ...bodyRows].map(formatTableRow);

    return `\n\n${markdownRows.join("\n")}\n\n`;
  },
});

export async function sceneMarkdownToHtml(markdown: string): Promise<string> {
  return (await marked.parse(markdown || "")) || "<p></p>";
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
