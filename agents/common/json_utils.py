"""Helpers for extracting JSON from agent / LLM text responses."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)
_BOX_PREFIX_RE = re.compile(r"^[\s│┃┆┊]*", re.MULTILINE)


def extract_json(text: str) -> Any:
    """Parse JSON from raw text, markdown fences, or prose-wrapped payloads.

    Agent crews often return ```json … ``` blocks or leading explanation.
    Raises json.JSONDecodeError if nothing parseable is found.
    """
    if text is None:
        raise json.JSONDecodeError("Expecting value", "", 0)

    cleaned = _BOX_PREFIX_RE.sub("", text).strip()
    if not cleaned:
        raise json.JSONDecodeError("Expecting value", text, 0)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for match in _FENCE_RE.finditer(cleaned):
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # First balanced object or array in the text
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise json.JSONDecodeError("Expecting value", cleaned[:80], 0)
