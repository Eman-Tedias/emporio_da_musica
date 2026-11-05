import json
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

ToolExecutor = Callable[[str, dict], dict]


class SchemaError(Exception):
    """The model answered, but not in the expected schema."""


class MaxStepsError(Exception):
    """The tool loop did not finish within the allowed number of steps."""


class Provider(Protocol):
    def structured(self, model: str, system: str, user: str, schema: type[BaseModel],
                   max_tokens: int) -> BaseModel: ...

    def tool_loop(self, model: str, system: str, user: str, tools: list[dict], execute: ToolExecutor,
                  max_steps: int, max_tokens: int) -> str: ...


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class OpenAIProvider:

    def __init__(self, api_key: str, timeout: float):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    def structured(self, model, system, user, schema, max_tokens):
        response = self.client.responses.parse(
            model=model, instructions=system, input=user, text_format=schema,
            max_output_tokens=max_tokens, reasoning={"effort": "low"},
        )
        if response.output_parsed is None:
            raise SchemaError(f"{model} returned no parsable output")
        return response.output_parsed

    def tool_loop(self, model, system, user, tools, execute, max_steps, max_tokens):
        specs = [{"type": "function", **tool} for tool in tools]
        items: list = [{"role": "user", "content": user}]
        for _ in range(max_steps):
            response = self.client.responses.create(
                model=model, instructions=system, input=items, tools=specs,
                max_output_tokens=max_tokens, reasoning={"effort": "low"},
            )
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return response.output_text
            items += response.output
            for call in calls:
                result = execute(call.name, json.loads(call.arguments or "{}"))
                items.append({"type": "function_call_output", "call_id": call.call_id, "output": to_json(result)})
        raise MaxStepsError(f"tool loop exceeded {max_steps} steps")

class GeminiProvider:
    def __init__(self, api_key: str, timeout: float):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    def structured(self, model, system, user, schema, max_tokens):
        response = self.client.models.generate_content(
            model=model, contents=user,
            config=self.types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_schema=schema, max_output_tokens=max_tokens,
            ),
        )
        if response.parsed is None:
            raise SchemaError(f"{model} returned no parsable output")
        return response.parsed

    def tool_loop(self, model, system, user, tools, execute, max_steps, max_tokens):
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**tool) for tool in tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        for _ in range(max_steps):
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
            calls = response.function_calls or []
            if not calls:
                return response.text or ""
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                result = json.loads(to_json(execute(call.name, dict(call.args or {}))))
                parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        raise MaxStepsError(f"tool loop exceeded {max_steps} steps")