"""Tests for agents.common.json_utils.extract_json."""

from __future__ import annotations

import json

import pytest

from agents.common.json_utils import extract_json


def test_plain_object() -> None:
    assert extract_json('{"listings": []}') == {"listings": []}


def test_markdown_fence() -> None:
    text = 'Here you go:\n```json\n{"listings": [{"id": 1}], "total_matching": 1}\n```\n'
    assert extract_json(text)["total_matching"] == 1


def test_box_drawing_prefixes() -> None:
    text = (
        "│  ```json\n"
        '│  {"listings": [], "search_url": "https://example.com"}\n'
        "│  ```\n"
    )
    data = extract_json(text)
    assert data["search_url"] == "https://example.com"


def test_prose_then_object() -> None:
    text = 'I found these parcels:\n{"listings": [1, 2], "total_matching": 2}\nDone.'
    assert extract_json(text)["listings"] == [1, 2]


def test_empty_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("   ")
