#!/usr/bin/env python3
"""Parse and edit the small frontmatter subset supported by memory notes.

The grammar is deliberately bounded: bare keys, top-level scalars/lists, and one
``metadata`` mapping containing scalars/lists. Lists may be single-line flow lists
or block lists of scalar values. Double quotes use JSON escapes; single quotes
escape a quote by doubling it. Plain null/none/~, true/false, and decimal numbers
retain their types. Other plain values are strings. Comments require whitespace
before ``#`` unless they occupy the whole line. YAML anchors, tags, nested
collections, block scalars, duplicate keys, and tabs in indentation are rejected.

No file I/O or governance policy lives here. Source spans let the caller change
only selected metadata nodes while retaining all other source text verbatim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


KEY_RE = re.compile(r"([\w.-]+):(?:[ ]+(.*)|$)")
NUMBER_RE = re.compile(r"[-+]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?\Z")
OPEN_RE = re.compile(r"\A---(?:\r\n|\n)")
CLOSE_RE = re.compile(r"^---(?:\r?\n|$)", re.MULTILINE)
FLOW_DELIMITER_RE = re.compile(r"[,\]]")


@dataclass(frozen=True)
class FieldSpan:
    start: int
    end: int
    indent: int


@dataclass
class FrontmatterDocument:
    data: dict[str, Any]
    body: str
    fields: dict[str, FieldSpan]
    metadata_fields: dict[str, FieldSpan]
    metadata_indent: int
    closing_offset: int
    newline: str | None


def _error(line: int, reason: str) -> ValueError:
    return ValueError(f"frontmatter line {line}: {reason}")


def _trailing_comment(rest: str, line: int) -> None:
    if rest and not (rest.isspace() or (rest[0].isspace() and rest.lstrip().startswith("#"))):
        raise _error(line, "unexpected trailing content after scalar/list")


def _quoted(value: str, line: int) -> tuple[str, int]:
    if value.startswith('"'):
        try:
            result, end = json.JSONDecoder().raw_decode(value)
        except ValueError as exc:
            raise _error(line, "invalid double-quoted scalar or escape") from exc
        return result, end
    result: list[str] = []
    index = 1
    while index < len(value):
        if value[index] != "'":
            result.append(value[index])
            index += 1
        elif index + 1 < len(value) and value[index + 1] == "'":
            result.append("'")
            index += 2
        else:
            return "".join(result), index + 1
    raise _error(line, "unterminated single-quoted scalar")


def _plain(value: str, line: int) -> Any:
    # An identifier cannot contain YAML delimiters/comments or be a number.
    # Common metadata values can therefore skip the punctuation checks.
    if value.isidentifier():
        lowered = value.lower()
        if lowered in {"null", "none"}:
            return None
        if lowered in {"true", "false"}:
            return lowered == "true"
        return value
    if "#" in value:
        value = re.split(r"\s+#", value, maxsplit=1)[0]
    value = value.rstrip()
    if not value or value.startswith("#"):
        return None
    unsupported = {"&": "anchor", "*": "alias", "!": "tag", "|": "block scalar", ">": "block scalar"}
    if value[0] in unsupported:
        raise _error(line, f"unsupported {unsupported[value[0]]}")
    if value[0] in "[{":
        raise _error(line, "unsupported nested collection")
    if (
        ":" in value and re.search(r":(?:\s|$)", value)
        or value[0] in "-?" and re.match(r"[-?](?:\s|$)", value)
    ):
        raise _error(line, "unsupported mapping or nested collection in scalar")
    if value.lower() in {"null", "none", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if NUMBER_RE.fullmatch(value):
        return float(value) if any(ch in value for ch in ".eE") else int(value)
    return value


def _flow_list(value: str, line: int) -> list[Any]:
    values: list[Any] = []
    index = 1
    while index < len(value):
        while index < len(value) and value[index].isspace():
            index += 1
        if index < len(value) and value[index] == "]":
            _trailing_comment(value[index + 1 :], line)
            return values
        if index >= len(value):
            break
        if value[index] in "\"'":
            item, used = _quoted(value[index:], line)
            index += used
        else:
            start = index
            delimiter = FLOW_DELIMITER_RE.search(value, index)
            index = delimiter.start() if delimiter else len(value)
            token = value[start:index].strip()
            if not token or token.startswith("#") or ("#" in token and re.search(r"\s+#", token)):
                raise _error(line, "empty item or multiline comment in flow list")
            if any(character in token for character in "[{}"):
                raise _error(line, "unsupported nested collection in flow list")
            item = _plain(token, line)
        values.append(item)
        while index < len(value) and value[index].isspace():
            index += 1
        if index < len(value) and value[index] == ",":
            index += 1
            continue
        if index < len(value) and value[index] == "]":
            _trailing_comment(value[index + 1 :], line)
            return values
        if index < len(value):
            raise _error(line, "unexpected trailing content in flow list")
    raise _error(line, "unterminated flow list; multiline flow lists are unsupported")


def parse_scalar(value: str, *, line: int = 1) -> Any:
    """Parse a scalar or a one-line flow list without coercing quoted values."""
    value = value.strip()
    if value.startswith(("'", '"')):
        result, end = _quoted(value, line)
        _trailing_comment(value[end:], line)
        return result
    if value.startswith("["):
        return _flow_list(value, line)
    return _plain(value, line)


class _Parser:
    def __init__(self, header: str, offset: int, *, capture_spans: bool):
        self.capture_spans = capture_spans
        self.lines = header.splitlines(keepends=True)
        self.line_info: list[tuple[int, str]] = []
        self.offsets: list[int] = []
        for index, line in enumerate(self.lines):
            if capture_spans:
                self.offsets.append(offset)
                offset += len(line)
            content = line.removesuffix("\n").removesuffix("\r")
            stripped = content.lstrip(" ")
            if stripped.startswith("\t"):
                raise _error(index + 2, "tab indentation is unsupported")
            self.line_info.append((len(content) - len(stripped), stripped))
        self.metadata_fields: dict[str, FieldSpan] = {}
        self.metadata_indent = 2

    def _info(self, index: int) -> tuple[int, str]:
        return self.line_info[index]

    def _skip(self, index: int) -> int:
        while index < len(self.lines) and (
            not self.line_info[index][1].strip() or self.line_info[index][1].lstrip().startswith("#")
        ):
            index += 1
        return index

    def _end(self, index: int) -> int:
        return self.offsets[index] + len(self.lines[index])

    def _block_list(self, index: int, indent: int) -> tuple[list[Any], int, int]:
        items: list[Any] = []
        last = index
        while index < len(self.lines):
            actual_indent, content = self._info(index)
            if actual_indent != indent or not re.match(r"-(?: |$)", content):
                break
            raw = content[1:].strip()
            if raw.startswith(('[', '{')):
                raise _error(index + 2, "unsupported nested collection in block list")
            item = parse_scalar(raw, line=index + 2)
            items.append(item)
            last = index
            index = self._skip(index + 1)
            if index < len(self.lines) and self._info(index)[0] > indent:
                raise _error(index + 2, "unsupported nested mapping or collection in block list")
        return items, index, self._end(last) if self.capture_spans else 0

    def mapping(self, index: int, indent: int, *, top: bool = False) -> tuple[dict[str, Any], dict[str, FieldSpan], int]:
        data: dict[str, Any] = {}
        spans: dict[str, FieldSpan] = {}
        index = self._skip(index)
        while index < len(self.lines):
            actual_indent, content = self._info(index)
            if actual_indent < indent:
                break
            if actual_indent != indent:
                raise _error(index + 2, "unexpected indentation or unsupported nested mapping")
            match = KEY_RE.fullmatch(content)
            if not match:
                raise _error(index + 2, "expected a bare key and scalar/list value")
            key, raw = match.group(1), match.group(2) or ""
            if key in data:
                raise _error(index + 2, f"duplicate key: {key}")
            start, end = (self.offsets[index], self._end(index)) if self.capture_spans else (0, 0)
            line = index + 2
            next_index = self._skip(index + 1)
            empty_value = not raw.strip() or raw.lstrip().startswith("#")
            if top and key == "metadata":
                if not empty_value:
                    raise _error(line, "metadata must be a block mapping")
                value: Any = {}
                if next_index < len(self.lines) and self._info(next_index)[0] > indent:
                    self.metadata_indent = self._info(next_index)[0]
                    value, self.metadata_fields, next_index = self.mapping(next_index, self.metadata_indent)
                    if self.metadata_fields:
                        end = max(field.end for field in self.metadata_fields.values())
            else:
                value = parse_scalar(raw, line=line)
                if next_index < len(self.lines):
                    next_indent, next_content = self._info(next_index)
                    if empty_value and next_indent >= indent and re.match(r"-(?: |$)", next_content):
                        value, next_index, end = self._block_list(next_index, next_indent)
                    elif next_indent > indent:
                        raise _error(next_index + 2, "unsupported nested mapping or collection")
            data[key] = value
            if self.capture_spans:
                spans[key] = FieldSpan(start, end, indent)
            index = next_index
        return data, spans, index


def _parse_document(text: str, *, capture_spans: bool) -> FrontmatterDocument | None:
    if text.partition("\n")[0].removesuffix("\r") != "---":
        return None
    opening = OPEN_RE.match(text)
    closing = CLOSE_RE.search(text, opening.end()) if opening else None
    if opening is None or closing is None:
        raise _error(1, "frontmatter is not terminated by a standalone --- line")
    parser = _Parser(text[opening.end() : closing.start()], opening.end(), capture_spans=capture_spans)
    data, fields, _ = parser.mapping(0, 0, top=True)
    newline = None
    if capture_spans:
        endings = {
            "\r\n" if line.endswith("\r\n") else "\n"
            for line in [opening.group(), *parser.lines, closing.group()]
            if line.endswith("\n")
        }
        newline = next(iter(endings)) if len(endings) == 1 else None
    return FrontmatterDocument(
        data=data,
        body=text[closing.end() :],
        fields=fields,
        metadata_fields=parser.metadata_fields,
        metadata_indent=parser.metadata_indent,
        closing_offset=closing.start(),
        newline=newline,
    )


def parse_document(text: str) -> FrontmatterDocument | None:
    """Read supported frontmatter and writer spans; return None for a legacy note."""
    return _parse_document(text, capture_spans=True)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Keep the existing reader API, including removal of leading body blank lines."""
    document = _parse_document(text, capture_spans=False)
    if document is None:
        return {}, text
    return document.data, document.body.lstrip("\r\n")


def replace_metadata_fields(text: str, fields: dict[str, Any]) -> str:
    """Replace complete authorized field nodes; do not reformat unrelated text."""
    document = parse_document(text)
    if document is None:
        raise ValueError("note has no YAML frontmatter")
    metadata = document.data.get("metadata", {})
    updates = {key: value for key, value in fields.items() if key not in metadata or metadata[key] != value}
    if not updates:
        return text
    if document.newline is None:
        raise ValueError("mixed frontmatter newline styles cannot be edited safely")
    newline = document.newline
    edits: list[tuple[int, int, str]] = []
    additions: list[str] = []
    for key, value in updates.items():
        span = document.metadata_fields.get(key)
        indent = span.indent if span else document.metadata_indent
        rendered = " " * indent + key + ": " + json.dumps(value, ensure_ascii=False) + newline
        if span:
            edits.append((span.start, span.end, rendered))
        else:
            additions.append(rendered)
    if additions:
        if "metadata" in document.fields:
            insertion = document.fields["metadata"].end
            rendered = "".join(additions)
        else:
            insertion = document.closing_offset
            rendered = "metadata:" + newline + "".join(additions)
        edits.append((insertion, insertion, rendered))
    after = text
    for start, end, replacement in sorted(edits, reverse=True):
        after = after[:start] + replacement + after[end:]
    verified = parse_document(after)
    expected = {**document.data, "metadata": {**metadata, **fields}}
    if verified is None or verified.data != expected or verified.body != document.body:
        raise ValueError("generated frontmatter failed read-back verification")
    return after
