"""Parsing for the concept-graph standard (graph spec 1.0).

Standard library only. This module reads the text forms the standard defines
and rejects anything else with a message that names the line.

Public API
----------
extract_frontmatter(text) -> (front_matter_text | None, body_text)
    Splits a SKILL.md at its '---' delimiters. Raises FrontmatterError when the
    opening delimiter has no closing one. Text without front matter returns
    (None, text).

parse_yaml_subset(text, source="<yaml>") -> dict | list | scalar
    Parses the YAML subset of field reference 1 of the graph standard:
    block mappings and block sequences, flow sequences and flow mappings of
    scalars, plain and double-quoted scalars, and '#' comments. Anything else
    raises YamlSubsetError with the line number: anchors, aliases, tags, block
    scalars, single-quoted strings, tab indentation, duplicate keys, nested
    flow collections, multi-line plain scalars and document markers. Plain
    scalars resolve as YAML 1.2's core schema does for true, false, null,
    integers and floats; every other plain scalar is a string. Empty text
    parses to {}. A top-level scalar is not in the subset.

SkillDoc(path, frontmatter, body, error)
    One parsed SKILL.md. 'frontmatter' is a dict or None. 'error' holds the
    reason the front matter could not be read, or None.

read_skill(path) -> SkillDoc
    Reads one SKILL.md. A front matter problem is stored in SkillDoc.error and
    never raised, so the body can still be read.

participation_bullets(body) -> list[(field, raw value)] | None
    The bullets of the '## Graph participation' section, as '- **field:** value'
    lines, in order and with duplicates kept. None when the section is absent.
    Values are returned as written, without interpretation.

parse_graph_participation(body) -> dict | None
    The same bullets as {field: raw value}. A duplicate field keeps the last
    value, so callers that must detect duplicates use participation_bullets.

realizes_block(body) -> dict | None
    The fenced 'realizes' block of a realization's body, parsed as a mapping.
    Raises YamlSubsetError when the block is outside the subset or when the
    body holds more than one such block.

load_json(path) -> Any
    Reads a JSON file as UTF-8. A duplicate key inside an object raises
    ValueError. Malformed JSON raises ValueError (json.JSONDecodeError).

validate_json_schema(instance, schema, root=None) -> list[str]
    Validates an instance against the JSON Schema subset that guidance keeps
    to: type, properties, required, additionalProperties, enum, const, items,
    pattern, minItems, uniqueItems, minimum, maximum, exclusiveMinimum,
    exclusiveMaximum, oneOf and $ref to a local '#/$defs/<name>'. Returns
    error strings with a JSON-path-like location; an empty list means the
    instance is valid. A schema keyword outside the subset raises
    SchemaSubsetError, so a schema is never checked more loosely than it says.
    Annotation keywords (title, description, default, examples, $schema,
    $comment, contractVersion, graphSpecVersion) are ignored. $id and
    definitions are outside the subset, as spec/README.md says.
"""

import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple


class YamlSubsetError(ValueError):
    """The text is outside the YAML subset, or is malformed."""


class FrontmatterError(ValueError):
    """The front matter of a SKILL.md is not delimited correctly."""


class SchemaSubsetError(ValueError):
    """A JSON Schema uses a keyword or form outside the guidance subset."""


# ---------------------------------------------------------------------------
# Front matter and SKILL.md
# ---------------------------------------------------------------------------

def extract_frontmatter(text: str) -> Tuple[Optional[str], str]:
    """Return (front matter text or None, body text)."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            front = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:])
            return front, body
    raise FrontmatterError("front matter opens with '---' but has no closing '---'")


@dataclass
class SkillDoc:
    path: Path
    frontmatter: Optional[dict]
    body: str
    error: Optional[str]


def read_skill(path) -> SkillDoc:
    """Read one SKILL.md. Content problems are stored in the result, not raised."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return SkillDoc(path, None, "", f"cannot read file: {exc}")
    try:
        front, body = extract_frontmatter(text)
    except FrontmatterError as exc:
        return SkillDoc(path, None, text, str(exc))
    if front is None:
        return SkillDoc(path, None, body, None)
    try:
        value = parse_yaml_subset(front, source=str(path))
    except YamlSubsetError as exc:
        return SkillDoc(path, None, body, str(exc))
    if not isinstance(value, dict):
        return SkillDoc(path, None, body, "front matter must be a mapping")
    return SkillDoc(path, value, body, None)


_PARTICIPATION_HEADING = re.compile(r"^## Graph participation\s*$")
_PARTICIPATION_BULLET = re.compile(r"^- \*\*([A-Za-z][A-Za-z0-9_]*):\*\*\s*(.*?)\s*$")
_SECTION_END = re.compile(r"^#{1,6} ")


def participation_bullets(body: str) -> Optional[List[Tuple[str, str]]]:
    """Return the '## Graph participation' bullets in order, or None if absent."""
    lines = body.splitlines()
    start = None
    for index, line in enumerate(lines):
        if _PARTICIPATION_HEADING.match(line.rstrip()):
            start = index
            break
    if start is None:
        return None
    bullets: List[Tuple[str, str]] = []
    for line in lines[start + 1:]:
        if _SECTION_END.match(line):
            break
        match = _PARTICIPATION_BULLET.match(line.rstrip())
        if match:
            bullets.append((match.group(1), match.group(2)))
    return bullets


def parse_graph_participation(body: str) -> Optional[dict]:
    bullets = participation_bullets(body)
    if bullets is None:
        return None
    return dict(bullets)


_REALIZES_BLOCK = re.compile(r"^```realizes[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)


def realizes_block(body: str) -> Optional[dict]:
    blocks = _REALIZES_BLOCK.findall(body)
    if not blocks:
        return None
    if len(blocks) > 1:
        raise YamlSubsetError("more than one 'realizes' block in the body")
    value = parse_yaml_subset(blocks[0], source="realizes block")
    if not isinstance(value, dict):
        raise YamlSubsetError("the 'realizes' block must be a mapping")
    return value


# ---------------------------------------------------------------------------
# YAML subset
# ---------------------------------------------------------------------------

_DQ_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t",
    "r": "\r", "b": "\b", "f": "\f", "0": "\0",
}
_KEY_SEP = re.compile(r":(?= |$)")
_INT = re.compile(r"[-+]?[0-9]+\Z")
_FLOAT = re.compile(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")
_RESERVED_START = "&*!|>%@`'"


def _err(no: int, message: str) -> YamlSubsetError:
    return YamlSubsetError(f"line {no}: {message}")


def _scan_dq(text: str, start: int, no: int) -> Tuple[str, int]:
    """Read a double-quoted string that opens at text[start]. Return (value, end)."""
    out: List[str] = []
    index = start + 1
    while index < len(text):
        ch = text[index]
        if ch == '"':
            return "".join(out), index + 1
        if ch == "\\":
            if index + 1 >= len(text):
                break
            esc = text[index + 1]
            if esc == "u":
                digits = text[index + 2:index + 6]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise _err(no, "\\u escape needs four hex digits")
                out.append(chr(int(digits, 16)))
                index += 6
                continue
            if esc not in _DQ_ESCAPES:
                raise _err(no, f"unsupported escape '\\{esc}' in a double-quoted string")
            out.append(_DQ_ESCAPES[esc])
            index += 2
            continue
        out.append(ch)
        index += 1
    raise _err(no, "unterminated double-quoted string")


def _opens_token(line: str, index: int) -> bool:
    prefix = line[:index].rstrip()
    return prefix == "" or prefix[-1] in ":[{,-"


def _strip_comment(line: str) -> str:
    """Remove a trailing comment, leaving quoted text alone."""
    in_dq = False
    index = 0
    while index < len(line):
        ch = line[index]
        if in_dq:
            if ch == "\\":
                index += 2
                continue
            if ch == '"':
                in_dq = False
        elif ch == '"' and _opens_token(line, index):
            in_dq = True
        elif ch == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
        index += 1
    return line.rstrip()


def _resolve_plain(text: str) -> Any:
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if text in ("null", "Null", "NULL", "~"):
        return None
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def _plain_scalar(text: str, no: int) -> Any:
    if text[0] in _RESERVED_START:
        raise _err(no, f"'{text[0]}' starts a construct outside the subset "
                       "(anchor, alias, tag, block scalar, single quote or reserved indicator)")
    if _KEY_SEP.search(text):
        raise _err(no, f"a plain value may not contain ': ' ({text!r})")
    return _resolve_plain(text)


def _flow_items(body: str, no: int) -> List[str]:
    items: List[str] = []
    buf: List[str] = []
    index = 0
    in_dq = False
    while index < len(body):
        ch = body[index]
        if in_dq:
            buf.append(ch)
            if ch == "\\" and index + 1 < len(body):
                buf.append(body[index + 1])
                index += 2
                continue
            if ch == '"':
                in_dq = False
        elif ch == '"':
            in_dq = True
            buf.append(ch)
        elif ch in "[]{}":
            raise _err(no, "flow collections may hold scalars only, not nested collections")
        elif ch == ",":
            items.append("".join(buf).strip(" "))
            buf = []
        else:
            buf.append(ch)
        index += 1
    if in_dq:
        raise _err(no, "unterminated double-quoted string in a flow collection")
    items.append("".join(buf).strip(" "))
    return items


def _flow_scalar(item: str, no: int) -> Any:
    if item == "":
        raise _err(no, "empty entry in a flow collection")
    if item.startswith('"'):
        value, end = _scan_dq(item, 0, no)
        if item[end:].strip(" "):
            raise _err(no, "unexpected text after a quoted string")
        return value
    if item[0] in _RESERVED_START:
        raise _err(no, f"'{item[0]}' starts a construct outside the subset")
    if _KEY_SEP.search(item):
        raise _err(no, "a flow sequence holds scalars only, so 'key: value' is not allowed here")
    return _resolve_plain(item)


def _flow_sequence(text: str, no: int) -> list:
    if not text.endswith("]"):
        raise _err(no, "a flow sequence must open with '[' and close with ']' on one line")
    body = text[1:-1]
    if body.strip(" ") == "":
        return []
    return [_flow_scalar(item, no) for item in _flow_items(body, no)]


def _flow_pair(item: str, no: int) -> Tuple[str, Any]:
    if item.startswith('"'):
        key, end = _scan_dq(item, 0, no)
        rest = item[end:].lstrip(" ")
        if not (rest == ":" or rest.startswith(": ")):
            raise _err(no, "a flow mapping entry needs 'key: value'")
        value_text = rest[1:].strip(" ")
    else:
        match = _KEY_SEP.search(item)
        if match is None:
            raise _err(no, "a flow mapping entry needs 'key: value'")
        key = item[:match.start()].strip(" ")
        value_text = item[match.end():].strip(" ")
    if key == "" or key[0] in _RESERVED_START:
        raise _err(no, f"unsupported key {key!r} in a flow mapping")
    if value_text == "":
        raise _err(no, f"flow mapping key {key!r} has no value")
    return key, _flow_scalar(value_text, no)


def _flow_mapping(text: str, no: int) -> dict:
    if not text.endswith("}"):
        raise _err(no, "a flow mapping must open with '{' and close with '}' on one line")
    body = text[1:-1]
    result: dict = {}
    if body.strip(" ") == "":
        return result
    for item in _flow_items(body, no):
        key, value = _flow_pair(item, no)
        if key in result:
            raise _err(no, f"duplicate key {key!r} in a flow mapping")
        result[key] = value
    return result


def _inline_value(text: str, no: int) -> Any:
    if text.startswith('"'):
        value, end = _scan_dq(text, 0, no)
        if text[end:].strip(" "):
            raise _err(no, "unexpected text after a quoted string")
        return value
    if text.startswith("'"):
        raise _err(no, "single-quoted strings are outside the subset; use double quotes")
    if text.startswith("["):
        return _flow_sequence(text, no)
    if text.startswith("{"):
        return _flow_mapping(text, no)
    return _plain_scalar(text, no)


def _split_key(content: str, no: int) -> Optional[Tuple[str, str]]:
    """Return (key, rest) for a 'key: value' line, or None if it is not a key line."""
    if content.startswith('"'):
        key, end = _scan_dq(content, 0, no)
        rest = content[end:].lstrip(" ")
        if rest == ":" or rest.startswith(": "):
            return key, rest[1:].strip(" ")
        return None
    match = _KEY_SEP.search(content)
    if match is None:
        return None
    key = content[:match.start()].rstrip(" ")
    if key == "" or key[0] in _RESERVED_START + "[{\"#?":
        raise _err(no, f"unsupported key {key!r}")
    return key, content[match.end():].strip(" ")


def _is_sequence_line(content: str) -> bool:
    return content == "-" or content.startswith("- ")


class _Parser:
    def __init__(self, lines: List[list]):
        self.lines = lines
        self.index = 0

    def parse(self) -> Any:
        if not self.lines:
            return {}
        if self.lines[0][1] in ("---", "..."):
            raise _err(self.lines[0][2], "document markers are outside the subset")
        value = self._block(self.lines[0][0])
        if self.index < len(self.lines):
            indent, _, no = self.lines[self.index]
            raise _err(no, "unexpected content; check the indentation")
        return value

    def _current(self):
        return self.lines[self.index]

    def _block(self, indent: int) -> Any:
        _, content, _ = self._current()
        if _is_sequence_line(content):
            return self._sequence(indent)
        return self._mapping(indent)

    def _child(self, parent_indent: int, sequence_may_align: bool) -> Any:
        if self.index >= len(self.lines):
            return None
        indent, content, _ = self._current()
        if indent > parent_indent:
            return self._block(indent)
        if sequence_may_align and indent == parent_indent and _is_sequence_line(content):
            return self._sequence(indent)
        return None

    def _mapping(self, indent: int) -> dict:
        result: dict = {}
        while self.index < len(self.lines) and self._current()[0] == indent:
            _, content, no = self._current()
            if _is_sequence_line(content):
                raise _err(no, "a sequence item where a mapping key is expected")
            split = _split_key(content, no)
            if split is None:
                raise _err(no, "expected 'key: value'")
            key, rest = split
            if key in result:
                raise _err(no, f"duplicate key {key!r}")
            self.index += 1
            if rest == "":
                result[key] = self._child(indent, sequence_may_align=True)
            else:
                result[key] = _inline_value(rest, no)
        if self.index < len(self.lines) and self._current()[0] > indent:
            raise _err(self._current()[2], "unexpected indentation")
        return result

    def _sequence(self, indent: int) -> list:
        result: list = []
        while self.index < len(self.lines) and self._current()[0] == indent:
            _, content, no = self._current()
            if not _is_sequence_line(content):
                raise _err(no, "a mapping key where a sequence item is expected")
            item = content[1:].strip(" ")
            if item == "":
                self.index += 1
                result.append(self._child(indent, sequence_may_align=False))
                continue
            item_indent = indent + (len(content) - len(content[1:].lstrip(" ")))
            if self._looks_like_mapping(item, no):
                self.lines[self.index] = [item_indent, item, no]
                result.append(self._mapping(item_indent))
            else:
                self.index += 1
                result.append(_inline_value(item, no))
        if self.index < len(self.lines) and self._current()[0] > indent:
            raise _err(self._current()[2], "unexpected indentation")
        return result

    @staticmethod
    def _looks_like_mapping(item: str, no: int) -> bool:
        if item.startswith(("[", "{")):
            return False
        return _split_key(item, no) is not None


def _tokenize(text: str) -> List[list]:
    lines: List[list] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        indent_text = raw[:len(raw) - len(raw.lstrip())]
        if "\t" in indent_text:
            raise _err(no, "tabs are outside the subset; indent with spaces")
        stripped = _strip_comment(raw)
        if stripped.strip(" ") == "":
            continue
        content = stripped.strip(" ")
        if content in ("---", "..."):
            raise _err(no, "document markers are outside the subset")
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append([indent, content, no])
    return lines


def parse_yaml_subset(text: str, source: str = "<yaml>") -> Any:
    """Parse the YAML subset of the graph standard. See the module docstring."""
    try:
        return _Parser(_tokenize(text)).parse()
    except YamlSubsetError as exc:
        raise YamlSubsetError(f"{source}: {exc}") from None


# ---------------------------------------------------------------------------
# JSON and the JSON Schema subset
# ---------------------------------------------------------------------------

def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def load_json(path) -> Any:
    """Read a UTF-8 JSON file. Duplicate keys and malformed text raise ValueError."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


_IGNORED_KEYWORDS = frozenset({
    "$schema", "$comment", "title", "description", "default", "examples",
    "contractVersion", "graphSpecVersion", "$defs",
})
_SUBSET_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "enum", "const",
    "items", "pattern", "minItems", "uniqueItems", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "oneOf", "$ref",
})
_BOUND_KEYWORDS = ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum")
_MAX_DEPTH = 64
_LOCAL_REF = re.compile(r"#/(\$defs)/([^/]+)\Z")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_type(value: Any, wanted: str) -> bool:
    if wanted == "string":
        return isinstance(value, str)
    if wanted == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if wanted == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if wanted == "boolean":
        return isinstance(value, bool)
    if wanted == "object":
        return isinstance(value, dict)
    if wanted == "array":
        return isinstance(value, list)
    if wanted == "null":
        return value is None
    raise SchemaSubsetError(f"unknown type {wanted!r} in a schema")


def _same(a: Any, b: Any) -> bool:
    """JSON equality: 1 and 1.0 are equal, true is not 1, and containers compare by content."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _resolve_ref(ref: Any, root: dict) -> Any:
    match = _LOCAL_REF.match(ref) if isinstance(ref, str) else None
    if match is None:
        raise SchemaSubsetError(f"$ref {ref!r} is outside the subset; only local "
                                "'#/$defs/<name>' references are allowed")
    target = root.get(match.group(1), {}).get(match.group(2))
    if target is None:
        raise SchemaSubsetError(f"$ref {ref!r} does not resolve")
    return target


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_bound(value: Any) -> bool:
    """A bound is a finite JSON number. NaN and Infinity are not JSON, and a boolean is not a number."""
    return _is_number(value) and math.isfinite(value)


def keyword_value_problems(schema: dict) -> List[str]:
    """Why a bound or uniqueItems keyword holds a value the subset does not allow, one message each."""
    problems = [f"'{key}' must be a finite number, not {json.dumps(schema[key])}"
                for key in _BOUND_KEYWORDS if key in schema and not _is_bound(schema[key])]
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        problems.append(f"'uniqueItems' must be true or false, not {json.dumps(schema['uniqueItems'])}")
    return problems


def _validate(instance: Any, schema: Any, root: dict, path: str, depth: int) -> List[str]:
    if depth > _MAX_DEPTH:
        raise SchemaSubsetError("schema nesting is too deep; a $ref may be cyclic")
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: no value is allowed here"]
    if not isinstance(schema, dict):
        raise SchemaSubsetError(f"schema at {path} must be an object or a boolean")
    unknown = sorted(set(schema) - _SUBSET_KEYWORDS - _IGNORED_KEYWORDS)
    if unknown:
        raise SchemaSubsetError(f"schema keyword(s) {', '.join(unknown)} at {path} are outside the subset")
    problems = keyword_value_problems(schema)
    if problems:
        raise SchemaSubsetError(f"{problems[0]} at {path}")

    errors: List[str] = []
    if "$ref" in schema:
        errors += _validate(instance, _resolve_ref(schema["$ref"], root), root, path, depth + 1)
    if "type" in schema:
        wanted = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(instance, name) for name in wanted):
            errors.append(f"{path}: expected {' or '.join(wanted)}, got {_type_name(instance)}")
            return errors
    if "const" in schema and not _same(instance, schema["const"]):
        errors.append(f"{path}: must equal {json.dumps(schema['const'])}")
    if "enum" in schema and not any(_same(instance, option) for option in schema["enum"]):
        errors.append(f"{path}: must be one of {json.dumps(schema['enum'])}")
    if "pattern" in schema and isinstance(instance, str):
        # ECMA's $ is the end of the input. Python's $ also matches before a final newline, so a
        # trailing unescaped $ is written as \Z to make "acme\n" fail the same way in both.
        pattern = re.sub(r"(?<!\\)\$$", r"\\Z", schema["pattern"])
        if not re.search(pattern, instance):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: must be at least {schema['minimum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be greater than {schema['exclusiveMinimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: must be at most {schema['maximum']}")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: must be less than {schema['exclusiveMaximum']}")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        for key, value in instance.items():
            child = f"{path}.{key}"
            if key in properties:
                errors += _validate(value, properties[key], root, child, depth + 1)
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append(f"{child}: property is not allowed")
                elif isinstance(extra, dict) or isinstance(extra, bool):
                    errors += _validate(value, extra, root, child, depth + 1)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s), has {len(instance)}")
        if schema.get("uniqueItems") is True:
            pair = next(((i, j) for i, j in itertools.combinations(range(len(instance)), 2)
                         if _same(instance[i], instance[j])), None)
            if pair is not None:
                errors.append(f"{path}: items {pair[0]} and {pair[1]} are equal, and items must be unique")
        if "items" in schema:
            items = schema["items"]
            if not isinstance(items, (dict, bool)):
                raise SchemaSubsetError(f"'items' at {path} must be one schema (tuple form is outside the subset)")
            for index, item in enumerate(instance):
                errors += _validate(item, items, root, f"{path}[{index}]", depth + 1)
    if "oneOf" in schema:
        branches = schema["oneOf"]
        matched = [branch for branch in branches if not _validate(instance, branch, root, path, depth + 1)]
        if len(matched) != 1:
            errors.append(f"{path}: must match exactly one oneOf branch, matched {len(matched)}")
    return errors


def validate_json_schema(instance: Any, schema: Any, root: Optional[dict] = None) -> List[str]:
    """Validate instance against a schema in the guidance subset. Empty list means valid."""
    base = root if root is not None else schema
    if not isinstance(base, dict):
        base = {}
    return _validate(instance, schema, base, "$", 0)
