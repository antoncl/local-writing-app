from __future__ import annotations

import re


RAW_HTML_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?>")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def validate_scene_markdown(markdown: str) -> list[str]:
    errors: list[str] = []
    if "\x00" in markdown:
        errors.append("Scene Markdown cannot contain null characters.")
    if markdown.startswith("---\n"):
        errors.append("Scene body Markdown must not include YAML front matter.")
    if RAW_HTML_RE.search(markdown):
        errors.append("Scene Markdown must not contain raw HTML.")

    errors.extend(_validate_tables(markdown))
    return errors


def _validate_tables(markdown: str) -> list[str]:
    errors: list[str] = []
    lines = markdown.splitlines()
    for index, line in enumerate(lines[:-1]):
        next_line = lines[index + 1]
        if not TABLE_SEPARATOR_RE.match(next_line):
            continue

        header_columns = _table_column_count(line)
        separator_columns = _table_column_count(next_line)
        if header_columns < 1:
            errors.append(f"Markdown table on line {index + 1} must have a header row.")
        if separator_columns != header_columns:
            errors.append(f"Markdown table on line {index + 1} has an inconsistent separator row.")

        row_index = index + 2
        while row_index < len(lines) and "|" in lines[row_index].strip():
            if _table_column_count(lines[row_index]) != header_columns:
                errors.append(f"Markdown table row on line {row_index + 1} has the wrong number of cells.")
            row_index += 1
    return errors


def _table_column_count(line: str) -> int:
    stripped = line.strip()
    if not stripped:
        return 0
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return len(_split_unescaped_pipes(stripped))


def _split_unescaped_pipes(value: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in value:
        if character == "\\" and not escaped:
            escaped = True
            current.append(character)
            continue
        if character == "|" and not escaped:
            cells.append("".join(current))
            current = []
            continue
        current.append(character)
        escaped = False
    cells.append("".join(current))
    return cells
