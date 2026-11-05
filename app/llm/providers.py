import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

ToolExecutor = Callable[[str, dict], dict]


class SchemaError(Exception):
    """The model answered, but not in the expected schema."""


class MaxStepsError(Exception):
    """The tool loop did not finish within the allowed number of steps."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0  # includes reasoning tokens, which are billed as output

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


class Provider(Protocol):
    def structured(self, model: str, system: str, user: str, schema: type[BaseModel],
                   max_tokens: int) -> tuple[BaseModel, Usage]: ...

    def tool_loop(self, model: str, system: str, user: str, tools: list[dict], execute: ToolExecutor,
                  max_steps: int, max_tokens: int) -> tuple[str, Usage]: ...


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class OpenAIProvider:

    def __init__(self, api_key: str, timeout: float):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)

    @staticmethod
    def _usage(response) -> Usage:
        usage = response.usage
        return Usage(usage.input_tokens, usage.output_tokens) if usage else Usage()

    def structured(self, model, system, user, schema, max_tokens):
        response = self.client.responses.parse(
            model=model, instructions=system, input=user, text_format=schema,
            max_output_tokens=max_tokens, reasoning={"effort": "low"},
        )
        if response.output_parsed is None:
            raise SchemaError(f"{model} returned no parsable output")
        return response.output_parsed, self._usage(response)

    def tool_loop(self, model, system, user, tools, execute, max_steps, max_tokens):
        specs = [{"type": "function", **tool} for tool in tools]
        items: list = [{"role": "user", "content": user}]
        usage = Usage()
        for _ in range(max_steps):
            response = self.client.responses.create(
                model=model, instructions=system, input=items, tools=specs,
                max_output_tokens=max_tokens, reasoning={"effort": "low"},
            )
            usage += self._usage(response)
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return response.output_text, usage
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

    @staticmethod
    def _usage(response) -> Usage:
        meta = response.usage_metadata
        if meta is None:
            return Usage()
        output = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
        return Usage(meta.prompt_token_count or 0, output)

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
        return response.parsed, self._usage(response)

    def tool_loop(self, model, system, user, tools, execute, max_steps, max_tokens):
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**tool) for tool in tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        usage = Usage()
        for _ in range(max_steps):
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
            usage += self._usage(response)
            calls = response.function_calls or []
            if not calls:
                return response.text or "", usage
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                result = json.loads(to_json(execute(call.name, dict(call.args or {}))))
                parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        raise MaxStepsError(f"tool loop exceeded {max_steps} steps")
