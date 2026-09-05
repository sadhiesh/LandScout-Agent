"""Keep native tool schemas free of ``strict``, which Bedrock cannot compile.

CrewAI hardcodes ``strict: True`` on every tool it sends over the native
function-calling path. Bedrock turns a strict schema into a constrained-decoding
grammar whose size grows exponentially with the property count, and
``landwatch_search``'s 22 properties compiled to 343.9MB against a 300MB cap.
The failure only surfaced as a gateway 400 at agent runtime, so it is pinned
here offline.

See ``docs/decisions/0010-drop-strict-from-native-tool-schemas.md``.
"""

from __future__ import annotations

from typing import Any

import pytest
from crewai.llms.providers.openai.completion import OpenAICompletion

from agents.common.llm import _NonStrictOpenAICompletion


@pytest.fixture(name="llm")
def _llm() -> _NonStrictOpenAICompletion:
    """A provider instance built without contacting the gateway."""
    return _NonStrictOpenAICompletion(
        model="claude-sonnet-4-5-20250929",
        base_url="https://gateway.invalid/v1",
        api_key="test-key",
    )


def _tool_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "landwatch_search",
            "description": "Search LandWatch.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
            },
        },
    }


def test_strict_is_stripped_from_converted_tools(
    llm: _NonStrictOpenAICompletion,
) -> None:
    tools = [_tool_schema({"state": {"type": "string"}})]

    upstream = OpenAICompletion._convert_tools_for_interference(llm, tools)
    converted = llm._convert_tools_for_interference(tools)

    # The upstream assertion is what gives this test teeth: if CrewAI ever stops
    # forcing strict, the override becomes dead code rather than a silent no-op.
    assert upstream[0]["function"]["strict"] is True
    assert "strict" not in converted[0]["function"]


def test_conversion_preserves_name_and_parameters(
    llm: _NonStrictOpenAICompletion,
) -> None:
    """Dropping ``strict`` must not drop the schema the model needs."""
    converted = llm._convert_tools_for_interference(
        [_tool_schema({"state": {"type": "string"}, "acres_min": {"type": "number"}})]
    )
    function = converted[0]["function"]

    assert function["name"] == "landwatch_search"
    assert set(function["parameters"]["properties"]) == {"state", "acres_min"}


def test_the_real_landwatch_tool_converts_without_strict(
    llm: _NonStrictOpenAICompletion,
) -> None:
    """The schema that actually broke the gateway, end to end through CrewAI."""
    from crewai.utilities.agent_utils import setup_native_tools
    from landwatch.tools import build_crewai_tool

    schemas, _, _ = setup_native_tools([build_crewai_tool()])

    converted = llm._convert_tools_for_interference(schemas)

    assert converted[0]["function"]["name"] == "landwatch_search"
    assert "strict" not in converted[0]["function"]
