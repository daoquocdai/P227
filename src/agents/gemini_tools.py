from __future__ import annotations

from typing import Any

from google.genai import types


def gemini_tool_from_definitions(definitions: list[dict[str, Any]]) -> types.Tool:
    """Adapt the repository's provider-neutral function definitions for Gemini."""
    declarations = []
    for definition in definitions:
        declarations.append(
            types.FunctionDeclaration(
                name=definition["name"],
                description=definition.get("description"),
                parameters_json_schema=definition.get("parameters", {"type": "object"}),
            )
        )
    return types.Tool(function_declarations=declarations)
